"""One-day-ahead chance that an area reaches 35°C.

The features are yesterday's temperatures, the recent run of weather, the
time of year, and the area's climate. Today's temperature is not an input.
The label is whether today's maximum reached 35°C.

Training summers are November 2016 to March 2022. Test summers are November
2022 to March 2026. A persistence forecast ("it was 35°C yesterday") and a
calendar forecast (how often this area is that hot in this month) are the
baselines. If the model does not beat them, the metrics say so.

The public priority score does not use this model. The weather forecast
already gives the next 16 days. The model is the checked, tracked estimate
for the day ahead when only recent observations are in hand.
"""

from __future__ import annotations

import json
import os
from datetime import date

import duckdb
import mlflow
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
)

from vhhs.paths import FEATURES, MARTS, REPORTS

SPLIT = date(2022, 11, 1)
FEATURE_COLUMNS = [
    "lag1_tmean",
    "lag1_tmax",
    "lag1_tmin",
    "lag3_tmean",
    "lag7_tmean",
    "doy_sin",
    "doy_cos",
    "latitude",
    "longitude",
    "t95_train",
    "threshold_c",
]


def learning_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = con.execute(
        """
        with base as (
            select
                lga_code,
                lga_name,
                date,
                latitude,
                longitude,
                threshold_c,
                temp_max_c,
                temp_min_c,
                temp_mean_c,
                very_hot_day,
                source,
                lag(temp_mean_c, 1) over w as lag1_tmean,
                lag(temp_max_c, 1) over w as lag1_tmax,
                lag(temp_min_c, 1) over w as lag1_tmin,
                avg(temp_mean_c) over (
                    partition by lga_code order by date
                    rows between 3 preceding and 1 preceding
                ) as lag3_tmean,
                avg(temp_mean_c) over (
                    partition by lga_code order by date
                    rows between 7 preceding and 1 preceding
                ) as lag7_tmean,
                lag(case when very_hot_day then 1 else 0 end, 1) over w as lag1_very_hot,
                row_number() over w as day_index
            from lga_daily
            window w as (partition by lga_code order by date)
        ),
        climate as (
            select lga_code, quantile_cont(temp_mean_c, 0.95) as t95_train
            from lga_daily
            where source = 'archive' and date < date '2022-11-01'
            group by lga_code
        )
        select
            b.lga_code,
            b.lga_name,
            b.date,
            b.source,
            b.latitude,
            b.longitude,
            b.threshold_c,
            c.t95_train,
            b.lag1_tmean,
            b.lag1_tmax,
            b.lag1_tmin,
            b.lag3_tmean,
            b.lag7_tmean,
            b.lag1_very_hot,
            case when b.very_hot_day then 1 else 0 end as very_hot,
            sin(2 * pi() * dayofyear(b.date) / 365.25) as doy_sin,
            cos(2 * pi() * dayofyear(b.date) / 365.25) as doy_cos
        from base b
        join climate c using (lga_code)
        where b.day_index >= 8
          and b.lag1_tmean is not null
          and b.lag7_tmean is not null
        """
    ).fetchdf()
    frame["date"] = pd.to_datetime(frame["date"]).dt.date
    return frame


def _summer(frame: pd.DataFrame) -> pd.DataFrame:
    months = frame["date"].map(lambda value: value.month)
    return frame[months.isin([11, 12, 1, 2, 3])].copy()


def _scores(y_true: np.ndarray, probability: np.ndarray) -> dict:
    return {
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "average_precision": float(average_precision_score(y_true, probability)),
        "brier": float(brier_score_loss(y_true, probability)),
    }


def train() -> dict:
    if not (MARTS / "lga_daily.parquet").exists():
        raise FileNotFoundError("run the pipeline before training")
    con = duckdb.connect()
    con.execute(
        "create table lga_daily as select * from read_parquet(?)",
        [str(MARTS / "lga_daily.parquet")],
    )
    frame = learning_frame(con)
    summer = _summer(frame)
    summer = summer[summer["source"] == "archive"]
    train_df = summer[summer["date"] < SPLIT]
    test_df = summer[summer["date"] >= SPLIT]
    if train_df.empty or test_df.empty:
        raise RuntimeError("the summer split produced an empty train or test set")
    if train_df["very_hot"].sum() < 30 or test_df["very_hot"].sum() < 30:
        raise RuntimeError("not enough 35°C days to validate a model")

    model = HistGradientBoostingClassifier(
        max_depth=3,
        learning_rate=0.08,
        max_iter=150,
        random_state=42,
    )
    model.fit(train_df[FEATURE_COLUMNS], train_df["very_hot"])
    test_probability = model.predict_proba(test_df[FEATURE_COLUMNS])[:, 1]
    model_metrics = _scores(test_df["very_hot"].to_numpy(), test_probability)

    # How often this area was hot in this month, estimated on the training summers only.
    climate = (
        train_df.assign(month=train_df["date"].map(lambda value: value.month))
        .groupby(["lga_code", "month"])["very_hot"]
        .mean()
    )
    climatology = test_df.apply(
        lambda row: climate.get((row["lga_code"], row["date"].month), train_df["very_hot"].mean()),
        axis=1,
    ).to_numpy()
    persistence = test_df["lag1_very_hot"].to_numpy(dtype=float)
    baseline = {
        "climatology": _scores(test_df["very_hot"].to_numpy(), climatology),
        "persistence": _scores(test_df["very_hot"].to_numpy(), persistence),
    }
    sample = test_df.sample(n=min(4000, len(test_df)), random_state=42)
    importance = permutation_importance(
        model,
        sample[FEATURE_COLUMNS],
        sample["very_hot"],
        n_repeats=5,
        random_state=42,
        scoring="average_precision",
    )
    importance_rows = sorted(
        (
            {"feature": name, "importance": float(value)}
            for name, value in zip(FEATURE_COLUMNS, importance.importances_mean, strict=True)
        ),
        key=lambda item: item["importance"],
        reverse=True,
    )

    # One-day-ahead probability for the first forecast day, from observations only.
    forecast_days = frame[frame["source"] == "forecast"]["date"]
    first_forecast = forecast_days.min() if len(forecast_days) else None
    probabilities = pd.DataFrame(columns=["lga_code", "date", "next_day_heat_probability"])
    if first_forecast is not None:
        outlook = frame[frame["date"] == first_forecast]
        probabilities = outlook[["lga_code", "date"]].copy()
        probabilities["next_day_heat_probability"] = model.predict_proba(
            outlook[FEATURE_COLUMNS]
        )[:, 1]

    FEATURES.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    probabilities.to_parquet(FEATURES / "next_day_probability.parquet", index=False)

    beats_persistence = model_metrics["average_precision"] > baseline["persistence"]["average_precision"]
    beats_climatology = model_metrics["average_precision"] > baseline["climatology"]["average_precision"]
    metrics = {
        "target": "area-day maximum reaches 35C, predicted from prior days only",
        "split": "train summers Nov 2016-Mar 2022; test summers Nov 2022-Mar 2026",
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_positive_rate": float(train_df["very_hot"].mean()),
        "test_positive_rate": float(test_df["very_hot"].mean()),
        "model": model_metrics,
        "baselines": baseline,
        "beats_persistence_on_average_precision": bool(beats_persistence),
        "beats_climatology_on_average_precision": bool(beats_climatology),
        "permutation_importance": importance_rows,
        "first_forecast_date": None if first_forecast is None else str(first_forecast),
        "features": FEATURE_COLUMNS,
    }
    (REPORTS / "model_metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")

    # MLflow 3 hides the local file store unless this is set. The file store
    # is what we want: no database server and nothing to pay for.
    os.environ["MLFLOW_ALLOW_FILE_STORE"] = "true"
    mlflow.set_tracking_uri((REPORTS / "mlruns").as_uri())
    mlflow.set_experiment("vic-heat-very-hot-day")
    with mlflow.start_run(run_name="hist-gradient-boosting"):
        mlflow.log_params(
            {
                "max_depth": 3,
                "learning_rate": 0.08,
                "max_iter": 150,
                "split": str(SPLIT),
            }
        )
        mlflow.log_metrics(
            {
                "roc_auc": model_metrics["roc_auc"],
                "average_precision": model_metrics["average_precision"],
                "brier": model_metrics["brier"],
                "persistence_average_precision": baseline["persistence"]["average_precision"],
                "climatology_average_precision": baseline["climatology"]["average_precision"],
                "test_positive_rate": metrics["test_positive_rate"],
            }
        )
        mlflow.sklearn.log_model(
            model,
            name="model",
            skops_trusted_types=[
                "sklearn.ensemble._hist_gradient_boosting.predictor.TreePredictor"
            ],
        )
    return metrics


def main() -> None:
    metrics = train()
    print(
        json.dumps(
            {
                "test_rows": metrics["test_rows"],
                "positive_rate": round(metrics["test_positive_rate"], 4),
                "model_ap": round(metrics["model"]["average_precision"], 4),
                "persistence_ap": round(metrics["baselines"]["persistence"]["average_precision"], 4),
                "climatology_ap": round(metrics["baselines"]["climatology"]["average_precision"], 4),
                "roc_auc": round(metrics["model"]["roc_auc"], 4),
                "beats_persistence": metrics["beats_persistence_on_average_precision"],
                "beats_climatology": metrics["beats_climatology_on_average_precision"],
                "top_feature": metrics["permutation_importance"][0]["feature"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
