"""Event-time three-day mean temperature in PyFlink.

Each area-day is an event. A watermark sits one second behind the event time,
and a range window of the current day plus the two days before it produces
the same three-day mean as the batch query. The job reads a bounded snapshot
of the events. Those events are the payload published to the Redpanda topic
``vhhs.temperature``; pass ``--kafka`` once that topic is loaded and the
Flink Kafka connector jar is on the classpath.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from vhhs.paths import MARTS, REPORTS, SNAPSHOT

KAFKA_TOPIC = "vhhs.temperature"
KAFKA_JAR_ENV = "VHHS_FLINK_KAFKA_JAR"


def load_events(lga_limit: int | None, start: str | None) -> pd.DataFrame:
    path = MARTS / "lga_daily.parquet"
    if not path.exists():
        path = SNAPSHOT / "history_daily.parquet"
        frame = duckdb.execute(
            """
            select lga_code, cast(date as date) as date, temp_mean_c
            from read_parquet(?)
            where temp_mean_c is not null
            order by date, lga_code
            """,
            [str(path)],
        ).df()
    else:
        frame = duckdb.execute(
            """
            select lga_code, cast(date as date) as date, temp_mean_c
            from read_parquet(?)
            where temp_mean_c is not null
            order by date, lga_code
            """,
            [str(path)],
        ).df()
    if start:
        frame = frame[pd.to_datetime(frame["date"]) >= pd.to_datetime(start)]
    if lga_limit:
        keep = sorted(frame["lga_code"].unique())[:lga_limit]
        frame = frame[frame["lga_code"].isin(keep)]
    return frame.reset_index(drop=True)


def duckdb_three_day(frame: pd.DataFrame) -> pd.DataFrame:
    con = duckdb.connect()
    con.register("events", frame)
    return con.execute(
        """
        select
            lga_code,
            date,
            case when row_number() over (partition by lga_code order by date) >= 3
                then avg(temp_mean_c) over (
                    partition by lga_code order by date
                    rows between 2 preceding and current row
                )
            end as mean_3d
        from events
        """
    ).df()


def _epoch_ms(value) -> int:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if not isinstance(value, datetime):
        value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp() * 1000)


def flink_three_day(frame: pd.DataFrame, sink: Path, kafka_bootstrap: str | None = None) -> pd.DataFrame:
    from pyflink.common import Duration, Types, WatermarkStrategy
    from pyflink.common.watermark_strategy import TimestampAssigner
    from pyflink.datastream import StreamExecutionEnvironment
    from pyflink.table import DataTypes, Schema, StreamTableEnvironment

    if sink.exists():
        shutil.rmtree(sink)
    sink.mkdir(parents=True)

    env = StreamExecutionEnvironment.get_execution_environment()
    env.set_parallelism(1)
    jar = os.environ.get(KAFKA_JAR_ENV)
    if kafka_bootstrap and jar:
        env.add_jars(Path(jar).resolve().as_uri())
    table_env = StreamTableEnvironment.create(env)
    table_env.get_config().set("parallelism.default", "1")

    if kafka_bootstrap:
        # The topic carries the same daily events. Bounded mode stops at the
        # latest offset so the CI job finishes.
        table_env.execute_sql(
            f"""
            CREATE TABLE events (
                lga_code STRING,
                ts_ms BIGINT,
                temp_mean_c DOUBLE,
                event_time AS TO_TIMESTAMP_LTZ(ts_ms, 3),
                WATERMARK FOR event_time AS event_time - INTERVAL '1' SECOND
            ) WITH (
                'connector' = 'kafka',
                'topic' = '{KAFKA_TOPIC}',
                'properties.bootstrap.servers' = '{kafka_bootstrap}',
                'properties.group.id' = 'vhhs-flink',
                'scan.startup.mode' = 'earliest-offset',
                'scan.bounded.mode' = 'latest-offset',
                'format' = 'json',
                'json.fail-on-missing-field' = 'false',
                'json.ignore-parse-errors' = 'true'
            )
            """
        )
    else:
        rows = [
            (str(code), _epoch_ms(day), float(temp))
            for code, day, temp in frame.itertuples(index=False, name=None)
        ]
        stream = env.from_collection(
            rows,
            type_info=Types.ROW_NAMED(
                ["lga_code", "ts_ms", "temp_mean_c"],
                [Types.STRING(), Types.LONG(), Types.DOUBLE()],
            ),
        )

        class _Assign(TimestampAssigner):
            def extract_timestamp(self, value, record_timestamp: int) -> int:
                return int(value[1])

        stream = stream.assign_timestamps_and_watermarks(
            WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(1)).with_timestamp_assigner(
                _Assign()
            )
        )
        schema = (
            Schema.new_builder()
            .column("lga_code", DataTypes.STRING())
            .column("ts_ms", DataTypes.BIGINT())
            .column("temp_mean_c", DataTypes.DOUBLE())
            .column_by_expression("event_time", "TO_TIMESTAMP_LTZ(ts_ms, 3)")
            .watermark("event_time", "event_time - INTERVAL '1' SECOND")
            .build()
        )
        table_env.create_temporary_view("events", table_env.from_data_stream(stream, schema))

    table_env.execute_sql(
        f"""
        CREATE TABLE three_day (
            lga_code STRING,
            event_time TIMESTAMP_LTZ(3),
            mean_3d DOUBLE
        ) WITH (
            'connector' = 'filesystem',
            'path' = '{sink.as_posix()}',
            'format' = 'json'
        )
        """
    )
    table_env.execute_sql(
        """
        INSERT INTO three_day
        SELECT
            lga_code,
            event_time,
            AVG(temp_mean_c) OVER (
                PARTITION BY lga_code
                ORDER BY event_time
                RANGE BETWEEN INTERVAL '2' DAY PRECEDING AND CURRENT ROW
            ) AS mean_3d
        FROM events
        """
    ).wait()
    parts = list(sink.rglob("*.json"))
    if not parts:
        # Filesystem connector sometimes writes files without the .json suffix.
        parts = [path for path in sink.rglob("*") if path.is_file() and not path.name.startswith(".")]
    records = []
    for path in parts:
        text = path.read_text().strip()
        if not text:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    if not records:
        raise RuntimeError(f"Flink wrote no rows to {sink}")
    output = pd.DataFrame(records)
    output["event_time"] = pd.to_datetime(output["event_time"], utc=True)
    output["date"] = output["event_time"].dt.date
    return output[["lga_code", "date", "mean_3d"]]


def compare(lga_limit: int | None, start: str | None, kafka_bootstrap: str | None) -> dict:
    events = load_events(lga_limit, start)
    expected = duckdb_three_day(events)
    sink = REPORTS / "flink" / "three_day"
    actual = flink_three_day(events, sink, kafka_bootstrap=kafka_bootstrap)
    expected["date"] = pd.to_datetime(expected["date"]).dt.strftime("%Y-%m-%d")
    actual["date"] = pd.to_datetime(actual["date"]).dt.strftime("%Y-%m-%d")
    merged = expected.merge(actual, on=["lga_code", "date"], how="inner", suffixes=("_duckdb", "_flink"))
    merged = merged.dropna(subset=["mean_3d_duckdb"])
    if merged.empty:
        raise RuntimeError("no overlapping three-day means to compare")
    gap = (merged["mean_3d_duckdb"] - merged["mean_3d_flink"]).abs()
    report = {
        "events": int(len(events)),
        "areas": int(events["lga_code"].nunique()),
        "compared_rows": int(len(merged)),
        "max_abs_diff_c": float(gap.max()),
        "mean_abs_diff_c": float(gap.mean()),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "flink_compare.json").write_text(json.dumps(report, indent=2) + "\n")
    if report["max_abs_diff_c"] > 1e-6:
        raise RuntimeError(f"Flink and DuckDB disagree by {report['max_abs_diff_c']}°C")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Flink three-day mean versus DuckDB")
    parser.add_argument("--lga-limit", type=int, default=None)
    parser.add_argument("--start", default=None, help="First date to include, YYYY-MM-DD")
    parser.add_argument("--kafka", default=None, help="Redpanda bootstrap servers")
    args = parser.parse_args()
    print(json.dumps(compare(args.lga_limit, args.start, args.kafka), indent=2))


if __name__ == "__main__":
    main()
