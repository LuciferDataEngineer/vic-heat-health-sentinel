"""Compare the training summers with the later summers.

Evidently checks whether the weather the model learned from still looks like
the weather it is scored on. A drift flag is a prompt to retrain, not a
statement that the forecast is wrong.
"""

from __future__ import annotations

import json
from datetime import date

import duckdb
from evidently.metric_preset import DataDriftPreset
from evidently.report import Report

from vhhs.model import FEATURE_COLUMNS, learning_frame
from vhhs.paths import MARTS, REPORTS

SPLIT = date(2022, 11, 1)


def _share_drifted(payload: dict) -> dict:
    """Pull the dataset-level drift flag out of Evidently's result dict."""
    metrics = payload.get("metrics") or []
    for metric in metrics:
        result = metric.get("result") or {}
        if "dataset_drift" in result:
            drifted = result.get("drift_by_columns") or {}
            drifted_count = sum(
                1 for column in drifted.values() if isinstance(column, dict) and column.get("drift_detected")
            )
            checked = len(drifted) or len(FEATURE_COLUMNS)
            return {
                "dataset_drift": bool(result["dataset_drift"]),
                "drifted_columns": drifted_count,
                "columns_checked": checked,
                "share_of_columns_drifted": drifted_count / checked if checked else None,
            }
    return {"dataset_drift": None, "drifted_columns": None, "columns_checked": None}


def monitor(sample_size: int = 12000) -> dict:
    con = duckdb.connect()
    con.execute(
        "create table lga_daily as select * from read_parquet(?)",
        [str(MARTS / "lga_daily.parquet")],
    )
    frame = learning_frame(con)
    summer = frame[frame["source"] == "archive"].copy()
    summer = summer[summer["date"].map(lambda value: value.month).isin([11, 12, 1, 2, 3])]
    reference = summer[summer["date"] < SPLIT]
    current = summer[summer["date"] >= SPLIT]
    reference = reference.sample(n=min(sample_size, len(reference)), random_state=42)
    current = current.sample(n=min(sample_size, len(current)), random_state=42)
    columns = FEATURE_COLUMNS
    report = Report(metrics=[DataDriftPreset()])
    report.run(
        reference_data=reference[columns],
        current_data=current[columns],
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    report.save_html(str(REPORTS / "drift_report.html"))
    summary = _share_drifted(report.as_dict())
    summary.update(
        {
            "reference": "summer days before November 2022",
            "current": "summer days from November 2022 onward",
            "reference_rows": int(len(reference)),
            "current_rows": int(len(current)),
            "columns": columns,
            "tool": "evidently DataDriftPreset",
        }
    )
    (REPORTS / "drift_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    print(json.dumps(monitor(), indent=2))


if __name__ == "__main__":
    main()
