"""Repository paths. Everything is relative to the repo root."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
SNAPSHOT = DATA / "snapshot"
RAW = DATA / "raw"
MARTS = DATA / "marts"
FEATURES = DATA / "features"
LAKE = DATA / "lake"
SERVING = DATA / "serving"
FEAST = DATA / "feast"
REPORTS = ROOT / "reports"
SITE = ROOT / "site"
FEAST_REPO = ROOT / "feast_repo"
DBT_DIR = ROOT / "dbt_project"
CONTRACTS = ROOT / "contracts"

MELBOURNE = "Australia/Melbourne"
