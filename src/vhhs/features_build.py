"""Materialise area features into the Feast online store.

The offline store is the parquet file. The online store is a local SQLite
file. Both are free and need no server. The feature server in Kubernetes
reads the same rows from the JSON export, so a demo does not have to ship
the Feast package inside the container.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from vhhs.paths import FEAST_REPO, FEATURES, SERVING

REPO_ROOT = FEAST_REPO.parent


def build_feature_table() -> Path:
    source = SERVING / "area_feature_source.parquet"
    probability = FEATURES / "next_day_probability.parquet"
    if not source.exists():
        raise FileNotFoundError("run the pipeline before building features")
    if not probability.exists():
        raise FileNotFoundError("run the model before building features")
    FEATURES.mkdir(parents=True, exist_ok=True)
    target = FEATURES / "area_features.parquet"
    duckdb.execute(
        """
        copy (
            select
                s.lga_code,
                s.event_timestamp,
                cast(s.priority_score as double) as priority_score,
                cast(s.people_65_plus as bigint) as people_65_plus,
                cast(s.very_hot_days_ahead as bigint) as very_hot_days_ahead,
                cast(s.health_alert_days_ahead as bigint) as health_alert_days_ahead,
                cast(s.forecast_max_c as double) as forecast_max_c,
                cast(s.avg_summer_very_hot_days as double) as avg_summer_very_hot_days,
                cast(s.poor_air_days as bigint) as poor_air_days,
                cast(s.pm25_mean_max as double) as pm25_mean_max,
                cast(coalesce(p.next_day_heat_probability, 0) as double)
                    as next_day_heat_probability
            from read_parquet(?) s
            left join read_parquet(?) p using (lga_code)
        ) to ? (format parquet)
        """,
        [str(source), str(probability), str(target)],
    )
    return target


def _feature_module():
    spec = importlib.util.spec_from_file_location("vhhs_feast_features", FEAST_REPO / "features.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load feast_repo/features.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def materialise() -> dict:
    target = build_feature_table()
    from feast import FeatureStore

    module = _feature_module()
    store = FeatureStore(repo_path=str(FEAST_REPO))
    store.apply([module.project, module.lga, module.area_heat])
    store.materialize(datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 12, 31, tzinfo=timezone.utc))
    sample = duckdb.execute(
        "select lga_code from read_parquet(?) order by priority_score desc limit 1",
        [str(target)],
    ).fetchone()[0]
    online = store.get_online_features(
        features=[
            "area_heat:priority_score",
            "area_heat:people_65_plus",
            "area_heat:very_hot_days_ahead",
            "area_heat:next_day_heat_probability",
        ],
        entity_rows=[{"lga_code": sample}],
    ).to_dict()
    report = {
        "offline": str(target.relative_to(REPO_ROOT)),
        "sample_lga": sample,
        "online": {key: values[0] for key, values in online.items()},
        "materialised_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (FEATURES / "online_sample.json").write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main() -> None:
    print(json.dumps(materialise(), indent=2, default=str))


if __name__ == "__main__":
    main()
