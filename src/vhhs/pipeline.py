"""Build the silver and gold tables from the committed snapshot.

DuckDB is the warehouse. The heat-health day uses the Victorian threshold.
The Excess Heat Factor is calculated on the same daily series so the two
definitions can be compared. The priority score is a transparent index, not
the output of the trained model: councils can see what moved a place up the list.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb
import pyarrow as pa

from vhhs.districts import district_for
from vhhs.paths import MARTS, REPORTS, SERVING, SNAPSHOT
from vhhs.quality import verify_manifest

SCORE_WEIGHTS = {
    "forecast_heat": 0.34,
    "unusual_for_the_time_of_year": 0.16,
    "typical_summer": 0.20,
    "who_lives_there": 0.22,
    "air": 0.08,
}


def _manifest() -> dict:
    return json.loads((SNAPSHOT.parent / "manifest.json").read_text())


def _prepare(con: duckdb.DuckDBPyConnection) -> None:
    verify_manifest()
    con.execute(
        "create table history as select lga_code, cast(date as date) as date, "
        "temp_max_c, temp_min_c, temp_mean_c, 'archive' as source "
        "from read_parquet(?)",
        [str(SNAPSHOT / "history_daily.parquet")],
    )
    con.execute(
        "create table forecast as select lga_code, cast(date as date) as date, "
        "temp_max_c, temp_min_c, temp_mean_c, apparent_max_c, precipitation_mm "
        "from read_parquet(?)",
        [str(SNAPSHOT / "forecast_daily.parquet")],
    )
    con.execute(
        "create table air as select lga_code, cast(date as date) as date, "
        "pm25_mean, pm25_max, ozone_8h_max, poor_particle_day, poor_ozone_day "
        "from read_parquet(?)",
        [str(SNAPSHOT / "air_quality_daily.parquet")],
    )
    con.execute(
        "create table census as select * from read_parquet(?)",
        [str(SNAPSHOT / "census_lga.parquet")],
    )
    points = json.loads((SNAPSHOT / "sample_points.json").read_text())
    district_rows = []
    for point in points:
        district, threshold, how = district_for(point["lga_name"], point["latitude"])
        district_rows.append(
            {
                "lga_code": point["lga_code"],
                "lga_name": point["lga_name"],
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "area_sqkm": point["area_sqkm"],
                "district": district,
                "threshold_c": threshold,
                "threshold_how": how,
            }
        )
    con.register(
        "areas",
        pa.table(
            {
                "lga_code": [row["lga_code"] for row in district_rows],
                "lga_name": [row["lga_name"] for row in district_rows],
                "latitude": [row["latitude"] for row in district_rows],
                "longitude": [row["longitude"] for row in district_rows],
                "area_sqkm": [row["area_sqkm"] for row in district_rows],
                "district": [row["district"] for row in district_rows],
                "threshold_c": [row["threshold_c"] for row in district_rows],
                "threshold_how": [row["threshold_how"] for row in district_rows],
            }
        ),
    )
    # Archive wins on any overlapping day. The forecast covers the outlook only.
    con.execute(
        """
        create table weather as
        select * from history
        union all
        select f.lga_code, f.date, f.temp_max_c, f.temp_min_c, f.temp_mean_c, 'forecast'
        from forecast f
        where not exists (
            select 1 from history h
            where h.lga_code = f.lga_code and h.date = f.date
        )
        """
    )


def _heat_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        create table daily as
        select
            w.lga_code,
            a.lga_name,
            a.latitude,
            a.longitude,
            a.district,
            a.threshold_c,
            a.threshold_how,
            w.date,
            w.temp_max_c,
            w.temp_min_c,
            w.temp_mean_c,
            w.source,
            lead(w.temp_min_c) over (partition by w.lga_code order by w.date) as next_tmin_c,
            row_number() over (partition by w.lga_code order by w.date) as day_index
        from weather w
        join areas a using (lga_code)
        """
    )
    con.execute(
        """
        create table climate as
        select
            lga_code,
            quantile_cont(temp_mean_c, 0.95) as t95
        from daily
        where date between date '2016-01-01' and date '2025-12-31'
        group by lga_code
        """
    )
    con.execute(
        """
        create table with_windows as
        select
            d.*,
            c.t95,
            case when d.day_index >= 3 then
                avg(d.temp_mean_c) over (
                    partition by d.lga_code order by d.date
                    rows between 2 preceding and current row
                )
            end as t3,
            case when d.day_index >= 33 then
                avg(d.temp_mean_c) over (
                    partition by d.lga_code order by d.date
                    rows between 32 preceding and 3 preceding
                )
            end as t30
        from daily d
        join climate c using (lga_code)
        """
    )
    con.execute(
        """
        create table with_ehf as
        select
            *,
            case
                when next_tmin_c is null then null
                else (temp_max_c + next_tmin_c) / 2.0
            end as heat_health_mean_c,
            case
                when t3 is null or t30 is null then null
                else (t3 - t95) * greatest(1.0, t3 - t30)
            end as ehf,
            temp_max_c >= 35 as very_hot_day,
            temp_max_c >= 40 as extreme_hot_day
        from with_windows
        """
    )
    con.execute(
        """
        create table severe_level as
        select lga_code, quantile_cont(ehf, 0.85) as ehf_severe
        from with_ehf
        where ehf > 0
          and source = 'archive'
          and date between date '2016-01-01' and date '2025-12-31'
        group by lga_code
        having count(*) >= 20
        """
    )
    con.execute(
        """
        create table lga_daily as
        select
            e.lga_code,
            e.lga_name,
            e.latitude,
            e.longitude,
            e.district,
            e.threshold_c,
            e.threshold_how,
            e.date,
            e.temp_max_c,
            e.temp_min_c,
            e.temp_mean_c,
            e.next_tmin_c,
            e.heat_health_mean_c,
            e.heat_health_mean_c >= e.threshold_c as health_alert_day,
            e.very_hot_day,
            e.extreme_hot_day,
            e.t3,
            e.t30,
            e.t95,
            e.ehf,
            s.ehf_severe,
            case
                when e.ehf is null or e.ehf <= 0 then null
                when s.ehf_severe is null then 'low'
                when e.ehf >= 3 * s.ehf_severe then 'extreme'
                when e.ehf >= s.ehf_severe then 'severe'
                else 'low'
            end as heatwave_category,
            e.source
        from with_ehf e
        left join severe_level s using (lga_code)
        """
    )


def _gold(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        create table usual_max as
        select
            lga_code,
            month(date) as month_of_year,
            day(date) as day_of_month,
            avg(temp_max_c) as usual_max_c
        from lga_daily
        where source = 'archive'
          and year(date) between 2016 and 2025
        group by 1, 2, 3
        """
    )
    con.execute(
        """
        create table summer_days as
        select
            lga_code,
            case when month(date) >= 11 then year(date) else year(date) - 1 end as summer_year,
            count(*) as n_days,
            count(*) filter (where health_alert_day) as health_alert_days,
            count(*) filter (where very_hot_day) as very_hot_days,
            count(*) filter (where heatwave_category in ('severe', 'extreme')) as severe_heatwave_days
        from lga_daily
        where source = 'archive'
          and month(date) in (11, 12, 1, 2, 3)
        group by 1, 2
        """
    )
    con.execute(
        """
        create table summer_typical as
        select
            lga_code,
            avg(health_alert_days) as avg_summer_health_alert_days,
            avg(very_hot_days) as avg_summer_very_hot_days,
            avg(severe_heatwave_days) as avg_summer_severe_heatwave_days,
            count(*) as summers
        from summer_days
        where n_days >= 140
          and summer_year between 2016 and 2025
        group by lga_code
        """
    )
    con.execute(
        """
        create table outlook as
        select
            f.lga_code,
            f.date,
            f.temp_max_c,
            f.temp_min_c,
            f.apparent_max_c,
            f.precipitation_mm,
            u.usual_max_c,
            d.heat_health_mean_c,
            d.health_alert_day,
            d.very_hot_day,
            d.extreme_hot_day,
            d.heatwave_category,
            d.ehf
        from forecast f
        left join usual_max u
          on u.lga_code = f.lga_code
         and u.month_of_year = month(f.date)
         and u.day_of_month = day(f.date)
        left join lga_daily d
          on d.lga_code = f.lga_code and d.date = f.date
        """
    )
    con.execute(
        """
        create table outlook_lga as
        select
            lga_code,
            count(*) as forecast_days,
            max(temp_max_c) as forecast_max_c,
            arg_max(date, temp_max_c) as forecast_max_date,
            avg(temp_max_c) as forecast_mean_max_c,
            avg(usual_max_c) as usual_mean_max_c,
            avg(temp_max_c - usual_max_c) as anomaly_c,
            count(*) filter (where health_alert_day) as health_alert_days_ahead,
            count(*) filter (where very_hot_day) as very_hot_days_ahead,
            count(*) filter (where extreme_hot_day) as extreme_hot_days_ahead,
            count(*) filter (where heatwave_category in ('severe', 'extreme'))
                as severe_heatwave_days_ahead,
            count(*) filter (where heatwave_category is not null) as heatwave_days_ahead,
            max(heat_health_mean_c) as max_heat_health_mean_c
        from outlook
        group by lga_code
        """
    )
    con.execute(
        """
        create table air_lga as
        select
            lga_code,
            count(*) filter (where poor_particle_day or poor_ozone_day) as poor_air_days,
            count(*) filter (where poor_particle_day) as poor_particle_days,
            count(*) filter (where poor_ozone_day) as poor_ozone_days,
            max(pm25_mean) as pm25_mean_max,
            max(ozone_8h_max) as ozone_8h_max,
            count(*) as air_days
        from air
        group by lga_code
        """
    )
    con.execute(
        """
        create table people as
        select
            c.lga_code,
            c.lga_name as census_name,
            c.persons,
            c.children_0_4,
            c.age_65_74 + c.age_75_84 + c.age_85_plus as people_65_plus,
            c.children_0_4 * 1.0 / nullif(c.persons, 0) as pct_children_0_4,
            (c.age_65_74 + c.age_75_84 + c.age_85_plus) * 1.0 / nullif(c.persons, 0) as pct_65_plus,
            c.lone_person_households,
            c.households,
            c.lone_person_households * 1.0 / nullif(c.households, 0) as pct_lone_households,
            (
                coalesce(c.pct_households_equivalised_under_500, 0)
                + coalesce(c.pct_households_equivalised_nil, 0)
            ) / 100.0 as pct_low_income_households,
            c.median_equivalised_household_income_weekly as median_income_weekly
        from census c
        """
    )
    # Percent ranks are within councils that have a real resident population.
    con.execute(
        """
        create table ranked as
        select
            a.lga_code,
            a.lga_name,
            a.latitude,
            a.longitude,
            a.area_sqkm,
            a.district,
            a.threshold_c,
            a.threshold_how,
            p.persons,
            p.children_0_4,
            p.people_65_plus,
            p.pct_children_0_4,
            p.pct_65_plus,
            p.lone_person_households,
            p.households,
            p.pct_lone_households,
            p.pct_low_income_households,
            p.median_income_weekly,
            o.forecast_days,
            o.forecast_max_c,
            o.forecast_max_date,
            o.forecast_mean_max_c,
            o.usual_mean_max_c,
            o.anomaly_c,
            coalesce(o.health_alert_days_ahead, 0) as health_alert_days_ahead,
            coalesce(o.very_hot_days_ahead, 0) as very_hot_days_ahead,
            coalesce(o.extreme_hot_days_ahead, 0) as extreme_hot_days_ahead,
            coalesce(o.severe_heatwave_days_ahead, 0) as severe_heatwave_days_ahead,
            coalesce(o.heatwave_days_ahead, 0) as heatwave_days_ahead,
            o.max_heat_health_mean_c,
            coalesce(s.avg_summer_health_alert_days, 0) as avg_summer_health_alert_days,
            coalesce(s.avg_summer_very_hot_days, 0) as avg_summer_very_hot_days,
            coalesce(s.avg_summer_severe_heatwave_days, 0) as avg_summer_severe_heatwave_days,
            coalesce(s.summers, 0) as summers,
            coalesce(q.poor_air_days, 0) as poor_air_days,
            coalesce(q.poor_particle_days, 0) as poor_particle_days,
            coalesce(q.poor_ozone_days, 0) as poor_ozone_days,
            q.pm25_mean_max,
            q.ozone_8h_max,
            percent_rank() over (
                order by p.people_65_plus * coalesce(s.avg_summer_very_hot_days, 0)
            ) as hist_rank,
            percent_rank() over (order by p.pct_65_plus) as rank_65,
            percent_rank() over (order by p.pct_children_0_4) as rank_children,
            percent_rank() over (order by p.pct_lone_households) as rank_lone,
            percent_rank() over (order by p.pct_low_income_households) as rank_income
        from areas a
        join people p using (lga_code)
        left join outlook_lga o using (lga_code)
        left join summer_typical s using (lga_code)
        left join air_lga q using (lga_code)
        where p.persons >= 100
        """
    )
    con.execute(
        """
        create table lga_priority as
        select
            *,
            least(1.0, greatest(0.0,
                0.55 * least(very_hot_days_ahead, 3) / 3.0
                + 0.25 * least(health_alert_days_ahead, 2) / 2.0
                + 0.20 * least(1.0, greatest(0.0, (forecast_max_c - 31.0) / 6.0))
            )) as heat_component,
            least(1.0, greatest(0.0, (coalesce(anomaly_c, 0) + 1.0) / 6.0)) as unusual_component,
            hist_rank as summer_component,
            (rank_65 + rank_children + rank_lone + rank_income) / 4.0 as vulnerability_component,
            least(1.0, poor_air_days / 2.0) as air_component
        from ranked
        """
    )
    con.execute(
        f"""
        create or replace table lga_priority as
        select
            *,
            100.0 * (
                {SCORE_WEIGHTS["forecast_heat"]} * heat_component
                + {SCORE_WEIGHTS["unusual_for_the_time_of_year"]} * unusual_component
                + {SCORE_WEIGHTS["typical_summer"]} * summer_component
                + {SCORE_WEIGHTS["who_lives_there"]} * vulnerability_component
                + {SCORE_WEIGHTS["air"]} * air_component
            ) as priority_score
        from lga_priority
        """
    )
    con.execute(
        """
        create table fortnight as
        select
            o.date,
            sum(o.temp_max_c * p.persons) / sum(p.persons) as forecast_high_c,
            sum(o.usual_max_c * p.persons) / sum(p.persons) as usual_high_c
        from outlook o
        join people p using (lga_code)
        where p.persons >= 100
        group by o.date
        order by o.date
        """
    )


def _headlines(con: duckdb.DuckDBPyConnection) -> dict:
    priority = con.execute("select * from lga_priority").fetchdf()
    fortnight = con.execute("select * from fortnight order by date").fetchdf()
    hottest = con.execute(
        """
        select
            p.lga_name,
            p.forecast_max_date,
            p.forecast_max_c,
            p.usual_mean_max_c,
            p.anomaly_c,
            u.usual_max_c
        from lga_priority p
        left join usual_max u
          on u.lga_code = p.lga_code
         and u.month_of_year = month(p.forecast_max_date)
         and u.day_of_month = day(p.forecast_max_date)
        order by p.forecast_max_c desc
        limit 1
        """
    ).fetchone()
    # A dangerous heat day, in the public figures, is a day of 35°C or more.
    # The health-alert day is the stricter Victorian threshold (hot day and a warm night).
    dangerous = priority[priority["very_hot_days_ahead"] > 0]
    health_alert = priority[priority["health_alert_days_ahead"] > 0]
    poor_air = priority[priority["poor_air_days"] > 0]
    top10 = priority.sort_values(
        ["priority_score", "people_65_plus"], ascending=[False, False]
    ).head(10)
    hot_summer = priority.sort_values(
        ["avg_summer_very_hot_days", "people_65_plus"], ascending=[False, False]
    ).head(10)
    persons = float(priority["persons"].sum())
    anomaly = float((priority["anomaly_c"] * priority["persons"]).sum() / persons)
    close = priority[
        (priority["very_hot_days_ahead"] == 0) & (priority["forecast_max_c"] >= 33)
    ]
    manifest = _manifest()
    status = "quiet"
    if len(dangerous) > 0:
        status = "prepare"
    elif len(close) > 0 or len(poor_air) > 0 or anomaly >= 2:
        status = "watch"

    def _area(row) -> dict:
        return {
            "lga_code": row["lga_code"],
            "lga_name": row["lga_name"],
            "priority_score": round(float(row["priority_score"]), 1),
            "people_65_plus": int(row["people_65_plus"]),
            "persons": int(row["persons"]),
            "children_0_4": int(row["children_0_4"]),
            "health_alert_days_ahead": int(row["health_alert_days_ahead"]),
            "very_hot_days_ahead": int(row["very_hot_days_ahead"]),
            "forecast_max_c": round(float(row["forecast_max_c"]), 1),
            "forecast_max_date": str(row["forecast_max_date"])[:10],
            "anomaly_c": round(float(row["anomaly_c"]), 1) if row["anomaly_c"] == row["anomaly_c"] else None,
            "avg_summer_very_hot_days": round(float(row["avg_summer_very_hot_days"]), 1),
            "avg_summer_health_alert_days": round(float(row["avg_summer_health_alert_days"]), 1),
            "poor_air_days": int(row["poor_air_days"]),
            "pct_65_plus": round(float(row["pct_65_plus"]) * 100, 1),
            "pct_children_0_4": round(float(row["pct_children_0_4"]) * 100, 1),
            "pct_lone_households": round(float(row["pct_lone_households"]) * 100, 1),
            "pct_low_income_households": round(float(row["pct_low_income_households"]) * 100, 1),
            "median_income_weekly": None
            if row["median_income_weekly"] != row["median_income_weekly"]
            else round(float(row["median_income_weekly"])),
            "district": row["district"],
            "threshold_c": float(row["threshold_c"]),
        }

    fortnight_rows = []
    for _, row in fortnight.iterrows():
        fortnight_rows.append(
            {
                "date": str(row["date"])[:10],
                "forecast_high_c": round(float(row["forecast_high_c"]), 1),
                "usual_high_c": round(float(row["usual_high_c"]), 1),
            }
        )
    summer_leader = priority.sort_values("avg_summer_very_hot_days", ascending=False).iloc[0]
    headlines = {
        "status": status,
        "updated_melbourne": manifest["access_time_melbourne"],
        "access_date": manifest["access_date"],
        "forecast_start": fortnight_rows[0]["date"] if fortnight_rows else None,
        "forecast_end": fortnight_rows[-1]["date"] if fortnight_rows else None,
        "areas_scored": int(len(priority)),
        "persons": int(persons),
        "people_65_plus": int(priority["people_65_plus"].sum()),
        "people_65_plus_in_dangerous_forecast": int(dangerous["people_65_plus"].sum())
        if len(dangerous)
        else 0,
        "areas_with_dangerous_heat": int(len(dangerous)),
        "people_65_plus_in_health_alert_forecast": int(health_alert["people_65_plus"].sum())
        if len(health_alert)
        else 0,
        "areas_with_health_alert": int(len(health_alert)),
        "people_65_plus_in_hottest_summer_areas": int(hot_summer["people_65_plus"].sum()),
        "persons_in_hottest_summer_areas": int(hot_summer["persons"].sum()),
        "areas_within_2c_of_35": int(len(close)),
        "areas_with_poor_air": int(len(poor_air)),
        "people_in_poor_air": int(poor_air["persons"].sum()) if len(poor_air) else 0,
        "people_65_plus_top10": int(top10["people_65_plus"].sum()),
        "persons_top10": int(top10["persons"].sum()),
        "anomaly_c_population_weighted": round(anomaly, 2),
        "hottest_area": hottest[0],
        "hottest_date": str(hottest[1])[:10],
        "hottest_c": round(float(hottest[2]), 1),
        "hottest_area_usual_mean_max_c": round(float(hottest[3]), 1),
        "hottest_area_anomaly_c": round(float(hottest[4]), 1),
        "hottest_day_usual_c": None if hottest[5] is None else round(float(hottest[5]), 1),
        "summer_leader": summer_leader["lga_name"],
        "summer_leader_very_hot_days": round(float(summer_leader["avg_summer_very_hot_days"]), 1),
        "summer_leader_people_65_plus": int(summer_leader["people_65_plus"]),
        "mean_summer_very_hot_days": round(float(priority["avg_summer_very_hot_days"].mean()), 2),
        "mean_summer_health_alert_days": round(
            float(priority["avg_summer_health_alert_days"].mean()), 2
        ),
        "fallback_thresholds": int((priority["threshold_how"] != "health.vic").sum()),
        "top10": [_area(row) for _, row in top10.iterrows()],
        "fortnight": fortnight_rows,
        "score_weights": SCORE_WEIGHTS,
    }
    return headlines


def _write_outputs(con: duckdb.DuckDBPyConnection, headlines: dict) -> None:
    MARTS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    SERVING.mkdir(parents=True, exist_ok=True)
    con.execute(f"copy lga_daily to '{MARTS / 'lga_daily.parquet'}' (format parquet)")
    con.execute(f"copy lga_priority to '{MARTS / 'lga_priority.parquet'}' (format parquet)")
    con.execute(f"copy fortnight to '{MARTS / 'fortnight.parquet'}' (format parquet)")
    con.execute(f"copy outlook to '{MARTS / 'outlook.parquet'}' (format parquet)")
    (REPORTS / "headline.json").write_text(json.dumps(headlines, indent=2) + "\n")
    # Feature rows for Feast. The timestamp is the Melbourne access time in UTC.
    updated = headlines["updated_melbourne"]
    stamp = datetime.strptime(updated, "%Y-%m-%dT%H:%M:%S%z")
    event_ts = stamp.astimezone(timezone.utc).replace(tzinfo=None)
    con.execute(
        f"""
        copy (
            select
                lga_code,
                timestamp '{event_ts.strftime("%Y-%m-%d %H:%M:%S")}' as event_timestamp,
                priority_score,
                people_65_plus,
                persons,
                health_alert_days_ahead,
                very_hot_days_ahead,
                forecast_max_c,
                anomaly_c,
                avg_summer_very_hot_days,
                poor_air_days,
                coalesce(pm25_mean_max, 0) as pm25_mean_max,
                pct_65_plus,
                vulnerability_component,
                heat_component
            from lga_priority
        ) to '{SERVING / "area_feature_source.parquet"}' (format parquet)
        """
    )
    features = con.execute(
        """
        select lga_code, lga_name, round(priority_score, 1) as priority_score,
               people_65_plus, persons, health_alert_days_ahead, very_hot_days_ahead,
               round(forecast_max_c, 1) as forecast_max_c,
               round(anomaly_c, 1) as anomaly_c,
               round(avg_summer_very_hot_days, 1) as avg_summer_very_hot_days,
               poor_air_days
        from lga_priority
        order by priority_score desc
        """
    ).fetchdf()
    records = json.loads(features.to_json(orient="records"))
    (SERVING / "area_features.json").write_text(json.dumps({"areas": records}, indent=2) + "\n")


def build() -> dict:
    con = duckdb.connect()
    _prepare(con)
    _heat_tables(con)
    _gold(con)
    headlines = _headlines(con)
    _write_outputs(con, headlines)
    _quality_gates(con, headlines)
    con.close()
    return headlines


def _quality_gates(con: duckdb.DuckDBPyConnection, headlines: dict) -> None:
    # Re-open is unnecessary; con is still open. Checks raise if the snapshot is unusable.
    duplicate = con.execute(
        "select count(*) from (select lga_code, date, count(*) c from lga_daily "
        "group by 1, 2 having count(*) > 1)"
    ).fetchone()[0]
    if duplicate:
        raise RuntimeError(f"{duplicate} duplicate area-days")
    out_of_range = con.execute(
        "select count(*) from lga_daily where temp_max_c < -20 or temp_max_c > 55 "
        "or temp_min_c < -20 or temp_min_c > 55"
    ).fetchone()[0]
    if out_of_range:
        raise RuntimeError(f"{out_of_range} temperatures outside -20 to 55°C")
    bad_score = con.execute(
        "select count(*) from lga_priority where priority_score < 0 or priority_score > 100"
    ).fetchone()[0]
    if bad_score:
        raise RuntimeError("priority score left the 0-100 range")
    if headlines["areas_scored"] < 70:
        raise RuntimeError("fewer than 70 areas were scored")
    short_forecast = con.execute(
        "select count(*) from (select lga_code from outlook group by 1 having count(*) < 14)"
    ).fetchone()[0]
    if short_forecast:
        raise RuntimeError(f"{short_forecast} areas have fewer than 14 forecast days")
    report = {
        "areas_scored": headlines["areas_scored"],
        "duplicate_area_days": duplicate,
        "temperatures_out_of_range": out_of_range,
        "scores_out_of_range": bad_score,
        "fallback_thresholds": headlines["fallback_thresholds"],
        "daily_rows": con.execute("select count(*) from lga_daily").fetchone()[0],
    }
    (REPORTS / "quality.json").write_text(json.dumps(report, indent=2) + "\n")


def main() -> None:
    headlines = build()
    print(
        json.dumps(
            {
                "status": headlines["status"],
                "hottest": [headlines["hottest_area"], headlines["hottest_c"], headlines["hottest_date"]],
                "anomaly_c": headlines["anomaly_c_population_weighted"],
                "dangerous_areas": headlines["areas_with_dangerous_heat"],
                "people_65_in_dangerous": headlines["people_65_plus_in_dangerous_forecast"],
                "top": [row["lga_name"] for row in headlines["top10"][:5]],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
