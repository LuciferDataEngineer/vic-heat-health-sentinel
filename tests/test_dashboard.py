"""The public page stays in plain language."""

import json
import re
from pathlib import Path

from vhhs.paths import REPORTS, SITE

BANNED = [
    "ehf",
    "flink",
    "duckdb",
    "mlflow",
    "feast",
    "dagster",
    "airflow",
    "watermark",
    "percentile",
    "climatology",
    "feature store",
    "redpanda",
    "kafka",
    "iceberg",
    "lightgbm",
    "scikit",
    "pipeline",
    "schema",
    " sla",
]


def _visible(html: str) -> str:
    without = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    without = re.sub(r"<style[\s\S]*?</style>", " ", without, flags=re.I)
    without = re.sub(r"<[^>]+>", " ", without)
    return without.lower()


def test_page_speaks_plainly_and_uses_melbourne_time():
    page = Path(SITE / "index.html").read_text()
    visible = _visible(page)
    for word in BANNED:
        assert word not in visible, word
    headline = json.loads((REPORTS / "headline.json").read_text())
    assert "melbourne time" in visible
    assert headline["hottest_area"].lower() in visible
    assert "35" in visible
    assert "last updated" in visible
    assert "what this means" in visible
    assert "sources" in visible
