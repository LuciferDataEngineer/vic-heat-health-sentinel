"""Figures rebuilt from the committed snapshot stay inside the real world."""

import json
from datetime import date

import duckdb

from vhhs.heat import excess_heat_factors
from vhhs.paths import MARTS, REPORTS
from vhhs.quality import verify_manifest


def test_manifest_matches_the_files():
    manifest = verify_manifest()
    assert manifest["sources"]
    assert all(source["free"] is True for source in manifest["sources"])
    start = date.fromisoformat(manifest["notes"]["forecast_start"])
    end = date.fromisoformat(manifest["notes"]["forecast_end"])
    assert (end - start).days >= 13


def test_mildura_january_2019_heatwave_is_in_the_record():
    frame = duckdb.execute(
        """
        select date, temp_max_c, temp_mean_c, t95, health_alert_day, very_hot_day, heatwave_category
        from read_parquet(?)
        where lga_name = 'Mildura'
          and date between date '2019-01-01' and date '2019-01-31'
        order by date
        """,
        [str(MARTS / "lga_daily.parquet")],
    ).df()
    assert frame["temp_max_c"].max() > 45
    assert bool(frame["health_alert_day"].fillna(False).any())
    assert "severe" in set(frame["heatwave_category"].dropna())
    # The warehouse EHF sign agrees with the Python reference on this month,
    # using the same 95th percentile the pipeline stored.
    series = duckdb.execute(
        """
        select temp_mean_c, ehf, t95
        from read_parquet(?)
        where lga_name = 'Mildura' and date between date '2018-11-01' and date '2019-01-31'
        order by date
        """,
        [str(MARTS / "lga_daily.parquet")],
    ).df()
    reference = excess_heat_factors(series["temp_mean_c"].tolist(), float(series["t95"].iloc[0]))
    compared = [
        (left, right)
        for left, right in zip(reference, series["ehf"].tolist(), strict=True)
        if left is not None and right is not None and right == right
    ]
    assert compared
    assert max(abs(left - right) for left, right in compared) < 1e-6


def test_headline_counts_are_internally_consistent():
    headline = json.loads((REPORTS / "headline.json").read_text())
    areas, older = duckdb.execute(
        """
        select
            count(*) filter (where very_hot_days_ahead > 0),
            coalesce(sum(people_65_plus) filter (where very_hot_days_ahead > 0), 0)
        from read_parquet(?)
        """,
        [str(MARTS / "lga_priority.parquet")],
    ).fetchone()
    assert headline["areas_with_dangerous_heat"] == areas
    assert headline["people_65_plus_in_dangerous_forecast"] == older
    assert headline["people_65_plus"] > 1_000_000
    assert len(headline["top10"]) == 10
    assert headline["top10"][0]["priority_score"] >= headline["top10"][-1]["priority_score"]
    assert date.fromisoformat(headline["forecast_end"]) > date.fromisoformat(headline["forecast_start"])
