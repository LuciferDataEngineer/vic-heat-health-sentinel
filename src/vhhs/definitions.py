"""Dagster assets for the heat-health platform.

Dagster is the orchestrator because the work is a graph of data products:
the checked snapshot, the marts, the Delta tables, the tracked model, the
drift report, the online features and the stakeholder page. Each one is an
asset with a check, which is a better fit here than a task schedule.
Project 3 already used Airflow for dataset-triggered batches.
"""

from dagster import AssetCheckResult, Definitions, asset, asset_check


@asset(group_name="ingest")
def validated_snapshot() -> str:
    from vhhs.quality import verify_manifest

    return verify_manifest()["access_date"]


@asset_check(asset=validated_snapshot)
def snapshot_checksums(validated_snapshot: str) -> AssetCheckResult:
    return AssetCheckResult(
        passed=bool(validated_snapshot),
        metadata={"access_date": validated_snapshot},
    )


@asset(group_name="warehouse", deps=[validated_snapshot])
def priority_marts() -> str:
    from vhhs.pipeline import build

    return build()["status"]


@asset_check(asset=priority_marts)
def priority_status_known(priority_marts: str) -> AssetCheckResult:
    return AssetCheckResult(passed=priority_marts in {"quiet", "watch", "prepare"})


@asset(group_name="lake", deps=[priority_marts])
def delta_lake() -> int:
    from vhhs.lake import publish

    return len(publish()["tables"])


@asset(group_name="mlops", deps=[priority_marts])
def tracked_model() -> float:
    from vhhs.model import train

    return train()["model"]["average_precision"]


@asset(group_name="mlops", deps=[tracked_model])
def drift_report() -> bool:
    from vhhs.drift import monitor

    summary = monitor()
    return summary.get("dataset_drift") is not None


@asset(group_name="serving", deps=[priority_marts, tracked_model])
def online_features() -> str:
    from vhhs.features_build import materialise

    return materialise()["sample_lga"]


@asset(group_name="serving", deps=[priority_marts])
def stakeholder_dashboard() -> str:
    from vhhs.dashboard import build_site

    build_site()
    return "site/index.html"


defs = Definitions(
    assets=[
        validated_snapshot,
        priority_marts,
        delta_lake,
        tracked_model,
        drift_report,
        online_features,
        stakeholder_dashboard,
    ],
    asset_checks=[snapshot_checksums, priority_status_known],
)
