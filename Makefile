PYTHON ?= python
export VHHS_ROOT := $(CURDIR)
export VHHS_DUCKDB := $(CURDIR)/data/warehouse/vhhs.duckdb

.PHONY: snapshot pipeline lake model drift features dbt dashboard lint test all flink bench

snapshot:
	$(PYTHON) -m vhhs.ingest

pipeline:
	$(PYTHON) -m vhhs.pipeline

lake:
	$(PYTHON) -m vhhs.lake

model:
	$(PYTHON) -m vhhs.model

drift:
	$(PYTHON) -m vhhs.drift

features:
	$(PYTHON) -m vhhs.features_build

dbt:
	mkdir -p data/warehouse
	dbt build --project-dir dbt_project --profiles-dir dbt_project

dashboard:
	$(PYTHON) -m vhhs.dashboard

lint:
	ruff check src tests

test: lint
	pytest

flink:
	$(PYTHON) -m vhhs.flink_job --lga-limit 4 --start 2024-06-01

bench:
	$(PYTHON) -m vhhs.benchmark --lga-limit 8 --start 2023-01-01

all: pipeline lake model drift features dbt dashboard

ci: lint pipeline lake model drift features dbt dashboard test
