"""Publish and read temperature events on Redpanda.

Invalid events go to ``vhhs.temperature.dlq`` and are not treated as weather.
The Flink job can consume the main topic when ``--kafka`` is set.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import duckdb
import jsonschema

from vhhs.paths import CONTRACTS, SNAPSHOT

TOPIC = "vhhs.temperature"
DLQ = "vhhs.temperature.dlq"
MELBOURNE = ZoneInfo("Australia/Melbourne")


def _validator() -> jsonschema.Draft202012Validator:
    schema = json.loads((CONTRACTS / "temperature_event.schema.json").read_text())
    return jsonschema.Draft202012Validator(schema)


def iter_events(limit: int | None = None):
    frames = []
    history = SNAPSHOT / "history_daily.parquet"
    forecast = SNAPSHOT / "forecast_daily.parquet"
    if history.exists():
        frames.append(("archive", history))
    if forecast.exists():
        frames.append(("forecast", forecast))
    if not frames:
        raise FileNotFoundError("snapshot parquet is missing")
    pieces = []
    for source, path in frames:
        pieces.append(
            duckdb.execute(
                """
                select lga_code, cast(date as varchar) as date,
                       temp_max_c, temp_min_c, temp_mean_c, ? as source
                from read_parquet(?)
                """,
                [source, str(path)],
            ).df()
        )
    import pandas as pd

    frame = pd.concat(pieces, ignore_index=True)
    if limit:
        frame = frame.head(limit)
    for row in frame.itertuples(index=False):
        local = datetime.strptime(row.date, "%Y-%m-%d").replace(tzinfo=MELBOURNE)
        yield {
            "lga_code": row.lga_code,
            "event_time": local.isoformat(),
            "temp_max_c": float(row.temp_max_c),
            "temp_min_c": float(row.temp_min_c),
            "temp_mean_c": float(row.temp_mean_c),
            "source": row.source,
        }


def produce(bootstrap: str, limit: int | None, dead_letter_demo: bool) -> dict:
    from kafka import KafkaProducer

    validator = _validator()
    producer = KafkaProducer(
        bootstrap_servers=bootstrap,
        value_serializer=lambda value: json.dumps(value).encode(),
    )
    accepted = 0
    rejected = 0
    for event in iter_events(limit):
        errors = sorted(validator.iter_errors(event), key=lambda item: list(item.path))
        topic = TOPIC
        if errors:
            topic = DLQ
            rejected += 1
        else:
            accepted += 1
        producer.send(topic, event)
    if dead_letter_demo:
        producer.send(DLQ, {"lga_code": "nope", "temp_max_c": 99})
        rejected += 1
    producer.flush()
    producer.close()
    return {"accepted": accepted, "rejected": rejected}


def consume(bootstrap: str, limit: int, topic: str) -> list[dict]:
    from kafka import KafkaConsumer

    consumer = KafkaConsumer(
        topic,
        bootstrap_servers=bootstrap,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        consumer_timeout_ms=8000,
        value_deserializer=lambda raw: json.loads(raw.decode()),
    )
    rows = []
    for message in consumer:
        rows.append(message.value)
        if len(rows) >= limit:
            break
    consumer.close()
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Redpanda temperature events")
    parser.add_argument("--bootstrap", default="localhost:9092")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--produce", action="store_true")
    parser.add_argument("--consume", action="store_true")
    parser.add_argument("--dead-letter-demo", action="store_true")
    parser.add_argument("--topic", default=TOPIC)
    args = parser.parse_args()
    if args.produce:
        print(json.dumps(produce(args.bootstrap, args.limit, args.dead_letter_demo)))
    if args.consume:
        rows = consume(args.bootstrap, args.limit, args.topic)
        print(json.dumps({"read": len(rows), "first": rows[0] if rows else None}))


if __name__ == "__main__":
    main()
