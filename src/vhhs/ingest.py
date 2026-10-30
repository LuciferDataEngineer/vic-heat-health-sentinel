"""Download the public snapshot used by the pipeline and the dashboard.

Nothing here is invented. A failed request is retried, then recorded. The
committed files under data/snapshot are what CI and GitHub Pages build from,
so a later reader does not need the APIs to be up.

Run ``python -m vhhs.ingest`` for a full refresh, or ``--forecast-only`` to
replace the next-16-day forecast and the air-quality forecast while keeping
the census and the historical temperature archive.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
import requests
from shapely.geometry import shape

from vhhs.paths import RAW, SNAPSHOT

USER_AGENT = "vic-heat-health-sentinel/0.1 (github.com/LuciferDataEngineer; research)"
MELBOURNE = ZoneInfo("Australia/Melbourne")
HISTORY_START = "2016-01-01"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
LGA_URL = "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/LGA/MapServer/0/query"
G01_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_2021_Census_G01_LGA/FeatureServer/0/query"
)
INCOME_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Income_including_government_allowances_by_2021_LGA/FeatureServer/0/query"
)
FAMILY_URL = (
    "https://geo.abs.gov.au/arcgis/rest/services/Hosted/"
    "ABS_Family_and_community_by_2021_LGA_Nov_2023/FeatureServer/1/query"
)

# Australian standards used when the hourly air-quality forecast is rolled up.
# PM2.5: National Environment Protection (Ambient Air Quality) Measure,
# 24-hour standard 25 µg/m³. Ozone: 0.065 ppm as an 8-hour average is about
# 130 µg/m³ (48 g/mol, 25°C). Open-Meteo reports both in µg/m³.
PM25_DAILY_STANDARD = 25.0
OZONE_8H_STANDARD = 130.0


def melbourne_now() -> datetime:
    return datetime.now(MELBOURNE)


def session() -> requests.Session:
    client = requests.Session()
    client.headers["User-Agent"] = USER_AGENT
    return client


def get_json(client: requests.Session, url: str, params: dict, timeout: int = 180) -> dict:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = client.get(url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            last_error = exc
            time.sleep(min(30, 2**attempt))
            continue
        if response.status_code == 200:
            return response.json()
        if response.status_code in {429, 500, 502, 503, 504}:
            last_error = requests.HTTPError(f"{response.status_code} {url}")
            time.sleep(min(30, 2**attempt))
            continue
        # A 400 from the archive API usually names the last available day.
        raise requests.HTTPError(
            f"{response.status_code} for {response.url}: {response.text[:400]}"
        )
    raise RuntimeError(f"giving up on {url}") from last_error


def sha256_file(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def largest_part(geometry):
    if geometry.geom_type == "Polygon":
        return geometry
    if geometry.geom_type == "MultiPolygon":
        return max(geometry.geoms, key=lambda part: part.area)
    return geometry


def fetch_boundaries(client: requests.Session) -> dict:
    payload = get_json(
        client,
        LGA_URL,
        {
            "where": "state_code_2021='2'",
            "outFields": "lga_code_2021,lga_name_2021,area_albers_sqkm",
            "outSR": "4326",
            "f": "geojson",
            "maxAllowableOffset": "0.008",
            "geometryPrecision": "4",
        },
    )
    features = [
        feature
        for feature in (payload.get("features") or [])
        if feature.get("geometry") and feature["geometry"].get("type")
    ]
    if len(features) < 70:
        raise RuntimeError(f"expected Victorian LGAs, got {len(features)} features")
    payload["features"] = features
    return payload


def arcgis_attributes(client: requests.Session, url: str, fields: str) -> list[dict]:
    payload = get_json(
        client,
        url,
        {
            "where": "lga_code_2021 LIKE '2%'",
            "outFields": fields,
            "returnGeometry": "false",
            "f": "json",
            "resultRecordCount": 500,
        },
    )
    return [row["attributes"] for row in payload.get("features", [])]


def fetch_census(client: requests.Session) -> list[dict]:
    g01 = arcgis_attributes(
        client,
        G01_URL,
        "lga_code_2021,lga_name_2021,tot_p_p,age_0_4_yr_p,age_65_74_yr_p,"
        "age_75_84_yr_p,age_85ov_p",
    )
    income = arcgis_attributes(
        client,
        INCOME_URL,
        "lga_code_2021,equiv_22021,equiv_32021,equiv_82021,persinc_22021,persinc_72021",
    )
    family = arcgis_attributes(
        client,
        FAMILY_URL,
        "lga_code_2021,hhtype_22021,hhtype_52021",
    )
    income_by_code = {str(row["lga_code_2021"]): row for row in income}
    family_by_code = {str(row["lga_code_2021"]): row for row in family}
    rows = []
    for person in g01:
        code = str(person["lga_code_2021"])
        pay = income_by_code.get(code, {})
        home = family_by_code.get(code, {})
        rows.append(
            {
                "lga_code": code,
                "lga_name": person["lga_name_2021"],
                "persons": _int(person.get("tot_p_p")),
                "children_0_4": _int(person.get("age_0_4_yr_p")),
                "age_65_74": _int(person.get("age_65_74_yr_p")),
                "age_75_84": _int(person.get("age_75_84_yr_p")),
                "age_85_plus": _int(person.get("age_85ov_p")),
                "median_equivalised_household_income_weekly": _float(pay.get("equiv_22021")),
                "pct_households_equivalised_under_500": _float(pay.get("equiv_32021")),
                "pct_households_equivalised_nil": _float(pay.get("equiv_82021")),
                "pct_persons_income_1_to_499": _float(pay.get("persinc_22021")),
                "pct_persons_nil_income": _float(pay.get("persinc_72021")),
                "lone_person_households": _int(home.get("hhtype_22021")),
                "households": _int(home.get("hhtype_52021")),
            }
        )
    if len(rows) < 70:
        raise RuntimeError(f"census returned {len(rows)} Victorian rows")
    under_500 = [
        row["pct_households_equivalised_under_500"]
        for row in rows
        if row["pct_households_equivalised_under_500"] is not None
    ]
    if under_500 and (min(under_500) < 0 or max(under_500) > 100):
        raise RuntimeError("income percentages are not on a 0-100 scale; refusing to guess")
    return rows


def _int(value) -> int | None:
    if value is None:
        return None
    return int(round(float(value)))


def _float(value) -> float | None:
    if value is None:
        return None
    return float(value)


def sample_points(boundaries: dict) -> list[dict]:
    points = []
    for feature in boundaries["features"]:
        props = feature["properties"]
        if not feature.get("geometry"):
            continue
        geometry = shape(feature["geometry"])
        if geometry.is_empty:
            continue
        part = largest_part(geometry)
        point = part.representative_point()
        points.append(
            {
                "lga_code": str(props["lga_code_2021"]),
                "lga_name": props["lga_name_2021"],
                "latitude": round(float(point.y), 5),
                "longitude": round(float(point.x), 5),
                "area_sqkm": float(props["area_albers_sqkm"]),
            }
        )
    return points


def latest_archive_day(client: requests.Session, point: dict) -> str:
    """ERA5 via Open-Meteo lags the present. Find the last day that returns."""
    yesterday = (melbourne_now().date() - timedelta(days=1)).isoformat()
    try:
        get_json(
            client,
            ARCHIVE_URL,
            {
                "latitude": point["latitude"],
                "longitude": point["longitude"],
                "start_date": yesterday,
                "end_date": yesterday,
                "daily": "temperature_2m_max",
                "timezone": "Australia/Melbourne",
            },
            timeout=60,
        )
        return yesterday
    except requests.HTTPError:
        pass
    # Walk back up to three weeks. The lag is usually about five days.
    for days_back in range(2, 22):
        day = (melbourne_now().date() - timedelta(days=days_back)).isoformat()
        try:
            get_json(
                client,
                ARCHIVE_URL,
                {
                    "latitude": point["latitude"],
                    "longitude": point["longitude"],
                    "start_date": day,
                    "end_date": day,
                    "daily": "temperature_2m_max",
                    "timezone": "Australia/Melbourne",
                },
                timeout=60,
            )
            return day
        except requests.HTTPError:
            continue
    raise RuntimeError("could not find a recent day on the Open-Meteo archive API")


def _daily_rows(payload: dict, fields: list[str]) -> list[dict]:
    daily = payload.get("daily") or {}
    times = daily.get("time") or []
    columns = {field: daily.get(field) or [] for field in fields}
    rows = []
    for index, day in enumerate(times):
        row = {"date": day}
        for field in fields:
            values = columns[field]
            row[field] = values[index] if index < len(values) else None
        rows.append(row)
    return rows


def fetch_history(client: requests.Session, point: dict, end_date: str) -> list[dict]:
    payload = get_json(
        client,
        ARCHIVE_URL,
        {
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "start_date": HISTORY_START,
            "end_date": end_date,
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean",
            "timezone": "Australia/Melbourne",
        },
    )
    rows = []
    for item in _daily_rows(
        payload, ["temperature_2m_max", "temperature_2m_min", "temperature_2m_mean"]
    ):
        if item["temperature_2m_max"] is None or item["temperature_2m_min"] is None:
            continue
        mean = item["temperature_2m_mean"]
        if mean is None:
            mean = (item["temperature_2m_max"] + item["temperature_2m_min"]) / 2
        rows.append(
            {
                "lga_code": point["lga_code"],
                "date": item["date"],
                "temp_max_c": float(item["temperature_2m_max"]),
                "temp_min_c": float(item["temperature_2m_min"]),
                "temp_mean_c": float(mean),
            }
        )
    return rows


def fetch_forecast(client: requests.Session, point: dict) -> list[dict]:
    payload = get_json(
        client,
        FORECAST_URL,
        {
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "daily": (
                "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                "apparent_temperature_max,precipitation_sum"
            ),
            "forecast_days": 16,
            "timezone": "Australia/Melbourne",
        },
    )
    rows = []
    fields = [
        "temperature_2m_max",
        "temperature_2m_min",
        "temperature_2m_mean",
        "apparent_temperature_max",
        "precipitation_sum",
    ]
    for item in _daily_rows(payload, fields):
        if item["temperature_2m_max"] is None or item["temperature_2m_min"] is None:
            continue
        mean = item["temperature_2m_mean"]
        if mean is None:
            mean = (item["temperature_2m_max"] + item["temperature_2m_min"]) / 2
        rows.append(
            {
                "lga_code": point["lga_code"],
                "date": item["date"],
                "temp_max_c": float(item["temperature_2m_max"]),
                "temp_min_c": float(item["temperature_2m_min"]),
                "temp_mean_c": float(mean),
                "apparent_max_c": _float(item["apparent_temperature_max"]),
                "precipitation_mm": _float(item["precipitation_sum"]),
            }
        )
    return rows


def fetch_air(client: requests.Session, point: dict) -> list[dict]:
    payload = get_json(
        client,
        AIR_URL,
        {
            "latitude": point["latitude"],
            "longitude": point["longitude"],
            "hourly": "pm2_5,ozone",
            "forecast_days": 5,
            "timezone": "Australia/Melbourne",
        },
    )
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    pm_values = hourly.get("pm2_5") or []
    ozone_values = hourly.get("ozone") or []
    by_day: dict[str, dict] = {}
    for index, stamp in enumerate(times):
        day = stamp[:10]
        bucket = by_day.setdefault(day, {"pm": [], "ozone": []})
        if index < len(pm_values) and pm_values[index] is not None:
            bucket["pm"].append(float(pm_values[index]))
        if index < len(ozone_values) and ozone_values[index] is not None:
            bucket["ozone"].append(float(ozone_values[index]))
    rows = []
    for day, bucket in sorted(by_day.items()):
        pm = bucket["pm"]
        ozone = bucket["ozone"]
        pm_mean = sum(pm) / len(pm) if pm else None
        ozone_8h = _max_rolling_mean(ozone, 8) if ozone else None
        rows.append(
            {
                "lga_code": point["lga_code"],
                "date": day,
                "pm25_mean": pm_mean,
                "pm25_max": max(pm) if pm else None,
                "ozone_8h_max": ozone_8h,
                "poor_particle_day": bool(pm_mean is not None and pm_mean >= PM25_DAILY_STANDARD),
                "poor_ozone_day": bool(ozone_8h is not None and ozone_8h >= OZONE_8H_STANDARD),
            }
        )
    return rows


def _max_rolling_mean(values: list[float], window: int) -> float | None:
    if len(values) < window:
        return sum(values) / len(values) if values else None
    totals = []
    running = sum(values[:window])
    totals.append(running / window)
    for index in range(window, len(values)):
        running += values[index] - values[index - window]
        totals.append(running / window)
    return max(totals)


def _map_pool(points: list[dict], worker, label: str, workers: int = 6) -> tuple[list, list]:
    done: list = []
    failed: list[dict] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, point): point for point in points}
        for count, future in enumerate(as_completed(futures), start=1):
            point = futures[future]
            try:
                done.extend(future.result())
            except Exception as exc:  # noqa: BLE001 - record and continue
                failed.append({"lga_code": point["lga_code"], "error": str(exc)[:300]})
                print(f"  {label} failed {point['lga_name']}: {exc}", flush=True)
            if count % 10 == 0 or count == len(points):
                print(f"  {label} {count}/{len(points)}", flush=True)
    return done, failed


def write_parquet(path, rows: list[dict], schema: pa.Schema) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = {field.name: [] for field in schema}
    for row in rows:
        for field in schema:
            columns[field.name].append(row.get(field.name))
    table = pa.table(columns, schema=schema)
    pq.write_table(table, path, compression="zstd")


def write_manifest(access: datetime, files: list[dict], sources: list[dict], notes: dict) -> None:
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    repo_root = SNAPSHOT.parents[1]
    payload = {
        "project": "vic-heat-health-sentinel",
        "access_date": access.date().isoformat(),
        "access_time_melbourne": access.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "notes": notes,
        "files": [],
        "sources": sources,
    }
    for item in files:
        path = item["path"]
        rows = item["rows"]
        payload["files"].append(
            {
                "path": str(path.relative_to(repo_root)),
                "rows": rows,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    target = SNAPSHOT.parent / "manifest.json"
    target.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {target}", flush=True)


def source_catalogue(access_date: str, history_end: str, forecast_start: str, forecast_end: str) -> list[dict]:
    return [
        {
            "name": "Open-Meteo forecast API",
            "publisher": "Open-Meteo",
            "url": "https://api.open-meteo.com/v1/forecast",
            "licence": "CC BY 4.0",
            "coverage": f"Daily temperature at one interior point in each Victorian LGA, {forecast_start} to {forecast_end}",
            "access_date": access_date,
            "free": True,
            "notes": "No API key. Upstream weather models via Open-Meteo.",
        },
        {
            "name": "Open-Meteo historical weather API (ERA5)",
            "publisher": "Open-Meteo, Copernicus Climate Change Service (ERA5)",
            "url": "https://archive-api.open-meteo.com/v1/archive",
            "licence": "CC BY 4.0",
            "coverage": f"Daily temperature, {HISTORY_START} to {history_end}, one interior point per Victorian LGA",
            "access_date": access_date,
            "free": True,
            "notes": "ERA5 reanalysis lags the present by several days, so the archive end date is the last day the API returned.",
        },
        {
            "name": "Open-Meteo air quality API (CAMS)",
            "publisher": "Open-Meteo, Copernicus Atmosphere Monitoring Service",
            "url": "https://air-quality-api.open-meteo.com/v1/air-quality",
            "licence": "CC BY 4.0",
            "coverage": "Hourly PM2.5 and ozone, aggregated to local days, next 5 days, one point per Victorian LGA",
            "access_date": access_date,
            "free": True,
            "notes": "Smoke is not a separate field. Fine-particle pollution (PM2.5) is the smoke proxy. EPA Victoria's keyed API is not used.",
        },
        {
            "name": "ABS ASGS 2021 Local Government Areas",
            "publisher": "Australian Bureau of Statistics",
            "url": "https://geo.abs.gov.au/arcgis/rest/services/ASGS2021/LGA/MapServer",
            "licence": "CC BY 4.0",
            "coverage": "Victorian LGA boundaries, generalised for the map, GDA2020 via Web Mercator query returned in WGS84",
            "access_date": access_date,
            "free": True,
            "notes": "Geometry simplified with maxAllowableOffset 0.008 degrees for the dashboard.",
        },
        {
            "name": "ABS Census 2021 General Community Profile G01",
            "publisher": "Australian Bureau of Statistics",
            "url": "https://geo.abs.gov.au/arcgis/rest/services/Hosted/ABS_2021_Census_G01_LGA/FeatureServer",
            "licence": "CC BY 4.0",
            "coverage": "Usual-resident population, children aged 0-4, and ages 65-74, 75-84 and 85+ by Victorian LGA",
            "access_date": access_date,
            "free": True,
            "notes": "Small random adjustments are applied by the ABS to protect privacy.",
        },
        {
            "name": "ABS Data by Region, income, 2021",
            "publisher": "Australian Bureau of Statistics",
            "url": "https://geo.abs.gov.au/arcgis/rest/services/Hosted/ABS_Income_including_government_allowances_by_2021_LGA/FeatureServer",
            "licence": "CC BY 4.0",
            "coverage": "Median equivalised household income and the share of households under $500 a week, Victorian LGAs",
            "access_date": access_date,
            "free": True,
            "notes": "Equivalised total household income, Census 2021.",
        },
        {
            "name": "ABS Data by Region, family and community, 2021",
            "publisher": "Australian Bureau of Statistics",
            "url": "https://geo.abs.gov.au/arcgis/rest/services/Hosted/ABS_Family_and_community_by_2021_LGA_Nov_2023/FeatureServer",
            "licence": "CC BY 4.0",
            "coverage": "Lone-person households and total households by Victorian LGA",
            "access_date": access_date,
            "free": True,
            "notes": "Table field hhtype_22021 is lone-person households.",
        },
        {
            "name": "Victorian heat-health temperature thresholds",
            "publisher": "Victorian Department of Health",
            "url": "https://www.health.vic.gov.au/environmental-health/heat-health-warning",
            "licence": "Public government page, cited; not a bulk download",
            "coverage": "District thresholds 30, 32 and 34°C and the council-to-district list",
            "access_date": access_date,
            "free": True,
            "notes": "Used only as the published temperature cut-offs. No health-outcome microdata.",
        },
    ]


def build_snapshot(forecast_only: bool = False) -> None:
    access = melbourne_now()
    SNAPSHOT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    client = session()

    print("boundaries and census", flush=True)
    if forecast_only and (SNAPSHOT / "lga_boundaries.geojson").exists():
        boundaries = json.loads((SNAPSHOT / "lga_boundaries.geojson").read_text())
        points = json.loads((SNAPSHOT / "sample_points.json").read_text())
    else:
        boundaries = fetch_boundaries(client)
        (SNAPSHOT / "lga_boundaries.geojson").write_text(json.dumps(boundaries))
        points = sample_points(boundaries)
        (SNAPSHOT / "sample_points.json").write_text(json.dumps(points, indent=2) + "\n")
        census = fetch_census(client)
        write_parquet(SNAPSHOT / "census_lga.parquet", census, CENSUS_SCHEMA)

    print("forecast", flush=True)
    forecast_rows, forecast_failed = _map_pool(
        points,
        lambda point: fetch_forecast(session(), point),
        "forecast",
    )
    if len(forecast_failed) > max(3, len(points) // 10):
        raise RuntimeError(f"too many forecast failures: {forecast_failed[:5]}")
    write_parquet(SNAPSHOT / "forecast_daily.parquet", forecast_rows, FORECAST_SCHEMA)

    print("air quality", flush=True)
    air_rows, air_failed = _map_pool(
        points, lambda point: fetch_air(session(), point), "air"
    )
    write_parquet(SNAPSHOT / "air_quality_daily.parquet", air_rows, AIR_SCHEMA)

    history_end = None
    history_failed: list[dict] = []
    if forecast_only and (SNAPSHOT / "history_daily.parquet").exists():
        history_meta_path = SNAPSHOT / "history_meta.json"
        history_end = json.loads(history_meta_path.read_text())["history_end"]
        history_rows_n = pq.read_metadata(SNAPSHOT / "history_daily.parquet").num_rows
    else:
        history_end = latest_archive_day(client, points[0])
        print(f"archive end date {history_end}", flush=True)
        history_rows, history_failed = _map_pool(
            points,
            lambda point: fetch_history(session(), point, history_end),
            "history",
            workers=4,
        )
        if len(history_failed) > max(3, len(points) // 10):
            raise RuntimeError(f"too many history failures: {history_failed[:5]}")
        write_parquet(SNAPSHOT / "history_daily.parquet", history_rows, HISTORY_SCHEMA)
        history_rows_n = len(history_rows)
        (SNAPSHOT / "history_meta.json").write_text(
            json.dumps({"history_start": HISTORY_START, "history_end": history_end}, indent=2)
            + "\n"
        )

    forecast_dates = sorted({row["date"] for row in forecast_rows})
    notes = {
        "history_start": HISTORY_START,
        "history_end": history_end,
        "forecast_start": forecast_dates[0] if forecast_dates else None,
        "forecast_end": forecast_dates[-1] if forecast_dates else None,
        "lga_sample_points": len(points),
        "history_failures": history_failed,
        "forecast_failures": forecast_failed,
        "air_failures": air_failed,
        "sample_point": (
            "Interior representative point of the largest polygon of each LGA. "
            "A geometric centroid can fall in the bay for coastal councils."
        ),
        "pm25_daily_standard_ugm3": PM25_DAILY_STANDARD,
        "ozone_8h_standard_ugm3": OZONE_8H_STANDARD,
    }
    (SNAPSHOT / "run_notes.json").write_text(json.dumps(notes, indent=2) + "\n")
    files = [
        {"path": SNAPSHOT / "lga_boundaries.geojson", "rows": len(boundaries["features"])},
        {"path": SNAPSHOT / "sample_points.json", "rows": len(points)},
        {
            "path": SNAPSHOT / "census_lga.parquet",
            "rows": pq.read_metadata(SNAPSHOT / "census_lga.parquet").num_rows,
        },
        {"path": SNAPSHOT / "history_daily.parquet", "rows": history_rows_n},
        {"path": SNAPSHOT / "forecast_daily.parquet", "rows": len(forecast_rows)},
        {"path": SNAPSHOT / "air_quality_daily.parquet", "rows": len(air_rows)},
        {"path": SNAPSHOT / "history_meta.json", "rows": 1},
        {"path": SNAPSHOT / "run_notes.json", "rows": 1},
    ]
    write_manifest(
        access,
        files,
        source_catalogue(
            access.date().isoformat(),
            history_end,
            notes["forecast_start"] or "",
            notes["forecast_end"] or "",
        ),
        notes,
    )


CENSUS_SCHEMA = pa.schema(
    [
        ("lga_code", pa.string()),
        ("lga_name", pa.string()),
        ("persons", pa.int64()),
        ("children_0_4", pa.int64()),
        ("age_65_74", pa.int64()),
        ("age_75_84", pa.int64()),
        ("age_85_plus", pa.int64()),
        ("median_equivalised_household_income_weekly", pa.float64()),
        ("pct_households_equivalised_under_500", pa.float64()),
        ("pct_households_equivalised_nil", pa.float64()),
        ("pct_persons_income_1_to_499", pa.float64()),
        ("pct_persons_nil_income", pa.float64()),
        ("lone_person_households", pa.int64()),
        ("households", pa.int64()),
    ]
)
HISTORY_SCHEMA = pa.schema(
    [
        ("lga_code", pa.string()),
        ("date", pa.string()),
        ("temp_max_c", pa.float64()),
        ("temp_min_c", pa.float64()),
        ("temp_mean_c", pa.float64()),
    ]
)
FORECAST_SCHEMA = pa.schema(
    [
        ("lga_code", pa.string()),
        ("date", pa.string()),
        ("temp_max_c", pa.float64()),
        ("temp_min_c", pa.float64()),
        ("temp_mean_c", pa.float64()),
        ("apparent_max_c", pa.float64()),
        ("precipitation_mm", pa.float64()),
    ]
)
AIR_SCHEMA = pa.schema(
    [
        ("lga_code", pa.string()),
        ("date", pa.string()),
        ("pm25_mean", pa.float64()),
        ("pm25_max", pa.float64()),
        ("ozone_8h_max", pa.float64()),
        ("poor_particle_day", pa.bool_()),
        ("poor_ozone_day", pa.bool_()),
    ]
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the open-data snapshot")
    parser.add_argument(
        "--forecast-only",
        action="store_true",
        help="Refresh the 16-day forecast and air quality; keep history and census",
    )
    args = parser.parse_args()
    build_snapshot(forecast_only=args.forecast_only)


if __name__ == "__main__":
    main()
