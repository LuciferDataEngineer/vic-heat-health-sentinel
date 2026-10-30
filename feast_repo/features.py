"""Area-level heat and vulnerability features for the online store."""

from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureView, Field, FileSource, Project
from feast.types import Float64, Int64
from feast.value_type import ValueType

ROOT = Path(__file__).resolve().parents[1]

area_heat_source = FileSource(
    name="area_heat_source",
    path=str(ROOT / "data" / "features" / "area_features.parquet"),
    timestamp_field="event_timestamp",
)

lga = Entity(
    name="lga",
    join_keys=["lga_code"],
    value_type=ValueType.STRING,
    description="Victorian local government area",
)

project = Project(name="vhhs", description="Victorian heat-health area features")

area_heat = FeatureView(
    name="area_heat",
    entities=[lga],
    ttl=timedelta(days=3650),
    schema=[
        Field(name="priority_score", dtype=Float64),
        Field(name="people_65_plus", dtype=Int64),
        Field(name="very_hot_days_ahead", dtype=Int64),
        Field(name="health_alert_days_ahead", dtype=Int64),
        Field(name="forecast_max_c", dtype=Float64),
        Field(name="avg_summer_very_hot_days", dtype=Float64),
        Field(name="poor_air_days", dtype=Int64),
        Field(name="pm25_mean_max", dtype=Float64),
        Field(name="next_day_heat_probability", dtype=Float64),
    ],
    online=True,
    source=area_heat_source,
    description="Latest heat, vulnerability and one-day-ahead heat probability for each area",
)
