"""Write the medallion tables as Delta Lake tables on the local disk.

delta-rs writes the Delta format without a Spark runtime, which is what makes
the lake practical in CI. DuckDB remains the query engine for the marts.
"""

from __future__ import annotations

import json

import pyarrow.parquet as pq
from deltalake import DeltaTable, write_deltalake

from vhhs.paths import LAKE, MARTS, REPORTS, SNAPSHOT

TABLES = {
    "bronze/history_daily": SNAPSHOT / "history_daily.parquet",
    "bronze/forecast_daily": SNAPSHOT / "forecast_daily.parquet",
    "bronze/air_quality_daily": SNAPSHOT / "air_quality_daily.parquet",
    "silver/lga_daily": MARTS / "lga_daily.parquet",
    "gold/lga_priority": MARTS / "lga_priority.parquet",
}


def publish() -> dict:
    written = []
    for name, source in TABLES.items():
        if not source.exists():
            raise FileNotFoundError(f"missing {source}; run the pipeline first")
        target = LAKE / name
        table = pq.read_table(source)
        write_deltalake(str(target), table, mode="overwrite")
        delta = DeltaTable(str(target))
        written.append(
            {
                "table": name,
                "version": delta.version(),
                "rows": delta.to_pyarrow_table().num_rows,
            }
        )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "lake.json").write_text(json.dumps(written, indent=2) + "\n")
    return {"tables": written}


def main() -> None:
    print(json.dumps(publish(), indent=2))


if __name__ == "__main__":
    main()
