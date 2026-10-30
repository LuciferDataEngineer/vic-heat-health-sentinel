"""Compare a Flink event-time window with the same DuckDB query.

The child process prints one JSON object: wall time for the calculation and
the process peak resident memory (VmHWM). Parent and child share nothing, so
the two engines are not measuring each other's heap.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

from vhhs.flink_job import duckdb_three_day, flink_three_day, load_events
from vhhs.paths import REPORTS


def peak_memory_kb() -> int:
    for line in open("/proc/self/status", encoding="utf-8"):
        if line.startswith("VmHWM:"):
            return int(line.split()[1])
    return 0


def run_engine(engine: str, lga_limit: int | None, start: str | None) -> dict:
    events = load_events(lga_limit, start)
    started = time.perf_counter()
    if engine == "duckdb":
        result = duckdb_three_day(events)
    elif engine == "flink":
        result = flink_three_day(events, REPORTS / "flink" / "benchmark")
    else:
        raise SystemExit(f"unknown engine {engine}")
    elapsed = time.perf_counter() - started
    return {
        "engine": engine,
        "events": int(len(events)),
        "areas": int(events["lga_code"].nunique()),
        "rows_out": int(len(result)),
        "seconds": round(elapsed, 3),
        "peak_memory_mb": round(peak_memory_kb() / 1024, 1),
    }


def benchmark(lga_limit: int | None, start: str | None) -> dict:
    rows = []
    for engine in ("duckdb", "flink"):
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "vhhs.benchmark",
                "--run",
                engine,
                *(["--lga-limit", str(lga_limit)] if lga_limit else []),
                *(["--start", start] if start else []),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        line = completed.stdout.strip().splitlines()[-1]
        rows.append(json.loads(line))
    duck = next(row for row in rows if row["engine"] == "duckdb")
    flink = next(row for row in rows if row["engine"] == "flink")
    summary = {
        "events": duck["events"],
        "areas": duck["areas"],
        "duckdb": duck,
        "flink": flink,
        "note": (
            "Same three-day trailing mean of daily temperature. "
            "DuckDB is one batch query. Flink is a streaming job with event-time "
            "watermarks over a bounded snapshot of the same rows. Peak memory is "
            "VmHWM for that process, which for Flink includes the JVM."
        ),
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "benchmark.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Flink versus DuckDB benchmark")
    parser.add_argument("--lga-limit", type=int, default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--run", choices=["duckdb", "flink"], default=None)
    args = parser.parse_args()
    if args.run:
        print(json.dumps(run_engine(args.run, args.lga_limit, args.start)))
        return
    print(json.dumps(benchmark(args.lga_limit, args.start), indent=2))


if __name__ == "__main__":
    main()
