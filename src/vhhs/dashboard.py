"""Static page for councils and health services. No tool names, no methods."""

from __future__ import annotations

import json
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from vhhs.paths import MARTS, REPORTS, SITE, SNAPSHOT

MELBOURNE = ZoneInfo("Australia/Melbourne")


def _load() -> dict:
    return json.loads((REPORTS / "headline.json").read_text())


def _commas(value: int) -> str:
    return f"{int(value):,}"


def _day(iso_date: str, with_year: bool = False) -> str:
    parsed = datetime.strptime(iso_date, "%Y-%m-%d")
    suffix = f" {parsed.year}" if with_year else ""
    return f"{parsed.strftime('%A')} {parsed.day} {parsed.strftime('%B')}{suffix}"


def _updated(stamp: str) -> str:
    parsed = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S%z")
    local = parsed.astimezone(MELBOURNE)
    hour = local.strftime("%I").lstrip("0") or "12"
    return (
        f"{hour}:{local.strftime('%M')} {local.strftime('%p').lower()}, "
        f"{_day(local.strftime('%Y-%m-%d'), with_year=True)} (Melbourne time)"
    )


def _cooler(anomaly: float) -> str:
    gap = abs(anomaly)
    if anomaly <= -0.05:
        return f"{gap:.1f}°C cooler than usual"
    if anomaly >= 0.05:
        return f"{gap:.1f}°C warmer than usual"
    return "about the same as usual"


def _bars(rows: list[dict], value_key: str, label_key: str, colour: str, suffix: str) -> str:
    width = 760
    row_h = 36
    left = 168
    right = 72
    height = 24 + row_h * len(rows)
    max_value = max(row[value_key] for row in rows) or 1
    parts = [
        f'<svg viewBox="0 0 {width} {height}" role="img" xmlns="http://www.w3.org/2000/svg">'
    ]
    for index, row in enumerate(rows):
        y = 16 + index * row_h
        value = row[value_key]
        bar_w = (width - left - right) * (value / max_value)
        parts.append(
            f'<text x="0" y="{y + 16}" class="bar-name">{escape(str(row[label_key]))}</text>'
            f'<rect x="{left}" y="{y}" width="{bar_w:.1f}" height="22" rx="4" fill="{colour}"/>'
            f'<text x="{left + bar_w + 8:.1f}" y="{y + 16}" class="bar-value">'
            f"{escape(str(value))}{escape(suffix)}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _lines(fortnight: list[dict]) -> str:
    width, height = 760, 280
    left, right, top, bottom = 48, 16, 16, 36
    forecast = [row["forecast_high_c"] for row in fortnight]
    usual = [row["usual_high_c"] for row in fortnight]
    lo = min(forecast + usual) - 1
    hi = max(forecast + usual) + 1
    span = hi - lo or 1
    plot_w = width - left - right
    plot_h = height - top - bottom

    def xy(index: int, value: float) -> tuple[float, float]:
        x = left + plot_w * (index / max(1, len(fortnight) - 1))
        y = top + plot_h * (1 - (value - lo) / span)
        return x, y

    def path(series: list[float]) -> str:
        return " ".join(
            ("M" if index == 0 else "L") + f"{xy(index, value)[0]:.1f},{xy(index, value)[1]:.1f}"
            for index, value in enumerate(series)
        )

    labels = []
    for index, row in enumerate(fortnight):
        if index % 3 != 0 and index != len(fortnight) - 1:
            continue
        x, _ = xy(index, forecast[index])
        day = datetime.strptime(row["date"], "%Y-%m-%d")
        labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" text-anchor="middle" class="axis">'
            f"{day.day} {day.strftime('%b')}</text>"
        )
    y_labels = []
    for tick in range(int(lo), int(hi) + 1, 2):
        _, y = xy(0, tick)
        y_labels.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" class="axis">{tick}°</text>'
        )
    last_f = xy(len(forecast) - 1, forecast[-1])
    last_u = xy(len(usual) - 1, usual[-1])
    return f"""
    <svg viewBox="0 0 {width} {height}" role="img" xmlns="http://www.w3.org/2000/svg">
      {''.join(y_labels)}
      <path d="{path(usual)}" fill="none" stroke="#8a8175" stroke-width="2.5" stroke-dasharray="5 4"/>
      <path d="{path(forecast)}" fill="none" stroke="#c2410c" stroke-width="3"/>
      <text x="{last_f[0] - 8}" y="{last_f[1] - 8}" text-anchor="end" class="series-label" fill="#c2410c">This forecast</text>
      <text x="{last_u[0] - 8}" y="{last_u[1] + 16}" text-anchor="end" class="series-label" fill="#8a8175">Usual for the date</text>
      {''.join(labels)}
    </svg>
    """


def _narrative(data: dict) -> dict:
    hottest_day = _day(data["hottest_date"], with_year=True)
    window = f"{_day(data['forecast_start'])} to {_day(data['forecast_end'], with_year=True)}"
    comparison = _cooler(data["anomaly_c_population_weighted"])
    usual = data.get("hottest_day_usual_c")
    usual_bit = (
        f" A usual high in {data['hottest_area']} on that date is {usual:.0f}°C."
        if usual is not None
        else ""
    )
    top_names = [row["lga_name"].replace(" (Vic.)", "") for row in data["top10"][:3]]
    top_phrase = f"{top_names[0]}, {top_names[1]} and {top_names[2]}"
    if data["status"] == "prepare":
        headline = (
            f"{_commas(data['areas_with_dangerous_heat'])} areas are heading into "
            f"dangerous heat, with {_commas(data['people_65_plus_in_dangerous_forecast'])} "
            "people aged 65 and over living there."
        )
        meaning = (
            "Open cooling centres in the areas at the top of the list, check on people "
            "who live alone, and make sure emergency departments and ambulance crews "
            "know which days will be hottest."
        )
        actions = [
            "Cooling centres: open them on the days an area reaches 35°C, and publish the hours today.",
            "Outreach: call or visit people who live alone in the top areas before the first hot day.",
            "Hospitals and ambulances: roster extra staff for the hottest one or two days, not the whole fortnight.",
        ]
    elif data["status"] == "watch":
        headline = "Heat is building. No area is at 35°C yet, but some are close."
        meaning = "Use the next day to confirm cooling centres and welfare lists before the temperature climbs."
        actions = [
            "Recheck the areas within a couple of degrees of 35°C each morning.",
            "Tell residents where to go if the forecast steps up.",
            "Keep an eye on air quality where fine particles are rising.",
        ]
    else:
        headline = "No dangerous heat is forecast in Victoria over the next 16 days."
        meaning = (
            f"There is no case for opening cooling centres on this forecast. "
            f"The useful work is preparation. Start with {top_phrase}. "
            f"{data['summer_leader']} averages {data['summer_leader_very_hot_days']:.0f} days "
            f"of 35°C or more in a summer, and {_commas(data['summer_leader_people_65_plus'])} "
            "people aged 65 and over live there."
        )
        actions = [
            f"Councils: confirm cooling-centre locations, hours and transport in {top_phrase} before December.",
            "Health services: the first hot spell is the one to roster for. This fortnight is not it.",
            "Smaller farming shires have the highest shares of older people living alone. Welfare lists can be checked while the weather is mild.",
            "Air quality: nothing in the next few days reaches an unhealthy level for fine particles or ozone.",
        ]
    return {
        "headline": headline,
        "window": window,
        "detail": (
            f"The hottest day in this forecast is {data['hottest_c']:.0f}°C in "
            f"{data['hottest_area']} on {hottest_day}.{usual_bit} "
            f"For a typical Victorian, daytime highs over this fortnight are {comparison}."
        ),
        "meaning": meaning,
        "actions": actions,
        "comparison": comparison,
        "kpis": _kpis(data, comparison, hottest_day, usual),
    }


def _kpis(data: dict, comparison: str, hottest_day: str, usual: float | None) -> list[dict]:
    usual_note = (
        f"A usual high in {data['hottest_area']} that day is {usual:.0f}°C."
        if usual is not None
        else "Still short of a 35°C day."
    )
    tone = "quiet" if data["people_65_plus_in_dangerous_forecast"] == 0 else "prepare"
    return [
        {
            "value": _commas(data["people_65_plus_in_dangerous_forecast"]),
            "label": "Older people facing a 35°C day",
            "note": "People aged 65 and over in areas forecast to reach 35°C in the next 16 days.",
            "tone": tone,
        },
        {
            "value": f"{data['hottest_c']:.0f}°C",
            "label": "Hottest day on the way",
            "note": f"{data['hottest_area']}, {hottest_day}. {usual_note}",
            "tone": "quiet" if data["hottest_c"] < 35 else "prepare",
        },
        {
            "value": comparison.replace(" than usual", ""),
            "label": "This fortnight versus a usual year",
            "note": "Daytime highs, weighted by where people live, against the same dates in 2016–2025.",
            "tone": "quiet" if data["anomaly_c_population_weighted"] < 1 else "watch",
        },
        {
            "value": _commas(data["people_65_plus_in_hottest_summer_areas"]),
            "label": "Older people in the ten hottest summers",
            "note": (
                f"They live in the areas that average the most 35°C days. "
                f"{data['summer_leader']} leads, with about {data['summer_leader_very_hot_days']:.0f} such days a summer."
            ),
            "tone": "watch",
        },
        {
            "value": _commas(data["areas_with_poor_air"]),
            "label": "Areas with unhealthy air",
            "note": "Fine-particle pollution or ozone above the Australian daily standard in the coming days.",
            "tone": "prepare" if data["areas_with_poor_air"] else "quiet",
        },
    ]


def _page(data: dict, story: dict) -> str:
    top = []
    for row in data["top10"]:
        name = row["lga_name"].replace(" (Vic.)", "")
        top.append(
            {
                "name": name,
                "score": row["priority_score"],
                "hot": row["avg_summer_very_hot_days"],
                "older": row["people_65_plus"],
            }
        )
    priority_chart = _bars(
        [{"label": row["name"], "value": row["score"]} for row in top],
        "value",
        "label",
        "#c2410c",
        "",
    )
    hot_chart = _bars(
        [
            {
                "label": row["name"],
                "value": row["hot"],
            }
            for row in top
        ],
        "value",
        "label",
        "#9a3412",
        "",
    )
    # Direct labels for the summer chart include the older-resident count via a second svg title.
    line = _lines(data["fortnight"])
    cards = []
    for card in story["kpis"]:
        cards.append(
            f"""
            <article class="kpi tone-{card['tone']}">
              <p class="kpi-value">{escape(card['value'])}</p>
              <h3>{escape(card['label'])}</h3>
              <p>{escape(card['note'])}</p>
            </article>
            """
        )
    actions = "".join(f"<li>{escape(item)}</li>" for item in story["actions"])
    status = data["status"]
    status_word = {"quiet": "Quiet fortnight", "watch": "Watch closely", "prepare": "Prepare now"}[
        status
    ]
    return f"""<!DOCTYPE html>
<html lang="en-AU">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Victoria heat and health</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
  <style>
    :root {{
      --paper: #f4efe4;
      --ink: #1c1915;
      --muted: #5e574c;
      --card: #fffdf8;
      --line: #e3d9c6;
      --quiet: #0f6e56;
      --watch: #8a5a00;
      --prepare: #9f1239;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Avenir Next", "Segoe UI", Helvetica, Arial, sans-serif;
      line-height: 1.45;
    }}
    main {{ max-width: 1120px; margin: 0 auto; padding: 28px 20px 64px; }}
    .banner {{
      background: var(--card);
      border: 1px solid var(--line);
      border-top: 8px solid var(--quiet);
      border-radius: 18px;
      padding: 22px 24px 18px;
    }}
    .banner.watch {{ border-top-color: var(--watch); }}
    .banner.prepare {{ border-top-color: var(--prepare); }}
    .status {{
      display: inline-block;
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      color: var(--quiet);
      margin: 0 0 8px;
    }}
    .banner.watch .status {{ color: var(--watch); }}
    .banner.prepare .status {{ color: var(--prepare); }}
    h1 {{ font-family: Georgia, "Iowan Old Style", serif; font-size: clamp(1.8rem, 3vw, 2.5rem); line-height: 1.15; margin: 0 0 10px; font-weight: 600; }}
    .detail {{ font-size: 1.08rem; margin: 0; max-width: 70ch; }}
    .updated {{ color: var(--muted); margin: 12px 0 0; font-size: 0.92rem; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(5, 1fr);
      gap: 12px;
      margin: 16px 0;
    }}
    .kpi {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 14px 14px 12px;
      min-height: 168px;
    }}
    .kpi-value {{
      font-family: Georgia, serif;
      font-size: clamp(1.7rem, 2.4vw, 2.2rem);
      margin: 0;
      line-height: 1.1;
    }}
    .tone-quiet .kpi-value {{ color: var(--quiet); }}
    .tone-watch .kpi-value {{ color: var(--watch); }}
    .tone-prepare .kpi-value {{ color: var(--prepare); }}
    .kpi h3 {{ margin: 8px 0 6px; font-size: 0.98rem; }}
    .kpi p {{ margin: 0; color: var(--muted); font-size: 0.88rem; }}
    .panel {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px 16px 12px;
      margin: 12px 0;
    }}
    .panel h2 {{ font-family: Georgia, serif; font-size: 1.45rem; margin: 0 0 4px; }}
    .insight {{ margin: 0 0 10px; color: var(--muted); }}
    #map {{ height: 540px; border-radius: 12px; }}
    .legend {{ display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 8px; color: var(--muted); font-size: 0.88rem; }}
    .swatch {{ width: 28px; height: 12px; border-radius: 99px; display: inline-block; }}
    .charts {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    .charts .wide {{ grid-column: 1 / -1; }}
    svg {{ width: 100%; height: auto; }}
    .bar-name, .bar-value, .axis, .series-label {{ font-size: 13px; font-family: "Avenir Next", "Segoe UI", sans-serif; }}
    .bar-name {{ fill: var(--ink); }}
    .bar-value {{ fill: var(--muted); }}
    .axis {{ fill: var(--muted); font-size: 12px; }}
    .meaning {{ border-left: 6px solid var(--quiet); }}
    .banner.watch ~ .meaning, .meaning.watch {{ border-left-color: var(--watch); }}
    .meaning.prepare {{ border-left-color: var(--prepare); }}
    .meaning ul {{ margin: 8px 0 0; padding-left: 18px; }}
    .meaning li {{ margin: 4px 0; }}
    footer {{ color: var(--muted); font-size: 0.86rem; }}
    footer ul {{ padding-left: 18px; }}
    @media (max-width: 980px) {{
      .kpis {{ grid-template-columns: 1fr 1fr; }}
      .charts {{ grid-template-columns: 1fr; }}
      #map {{ height: 420px; }}
    }}
    @media (max-width: 640px) {{
      .kpis {{ grid-template-columns: 1fr; }}
      .kpi {{ min-height: 0; }}
    }}
  </style>
</head>
<body>
<main>
  <header class="banner {status}">
    <p class="status">{escape(status_word)}</p>
    <h1>{escape(story['headline'])}</h1>
    <p class="detail">{escape(story['detail'])}</p>
    <p class="updated">Last updated {_updated(data['updated_melbourne'])}. Forecast window: {escape(story['window'])}.</p>
  </header>
  <section class="kpis">
    {''.join(cards)}
  </section>
  <section class="panel">
    <h2>Where to prepare first</h2>
    <p class="insight">Darker areas combine a hotter summer with more people who are hit harder by heat: older residents, young children, people living alone, and households on low incomes. The next 16 days do not override that picture when the forecast itself is mild.</p>
    <div id="map"></div>
    <div class="legend">
      <span>Lower priority</span>
      <span class="swatch" style="background:#f6e7c1"></span>
      <span class="swatch" style="background:#f0b56a"></span>
      <span class="swatch" style="background:#e07a3d"></span>
      <span class="swatch" style="background:#c2410c"></span>
      <span class="swatch" style="background:#7c2d12"></span>
      <span>Prepare here first</span>
    </div>
  </section>
  <section class="charts">
    <article class="panel">
      <h2>Ten areas to prepare first</h2>
      <p class="insight">A higher number means prepare here sooner. It is not a prediction of illness.</p>
      {priority_chart}
    </article>
    <article class="panel">
      <h2>How many 35°C days a typical summer brings</h2>
      <p class="insight">Same ten areas. Some are here because summer is fierce. Others are here because so many older people live there.</p>
      {hot_chart}
    </article>
    <article class="panel wide">
      <h2>This fortnight is {escape(comparison_phrase(data))}</h2>
      <p class="insight">{escape(fortnight_note(data))}</p>
      {line}
    </article>
  </section>
  <section class="panel meaning {status}">
    <h2>What this means</h2>
    <p>{escape(story['meaning'])}</p>
    <ul>{actions}</ul>
  </section>
  <footer class="panel">
    <h2>Sources</h2>
    <ul>
      <li>Temperature forecast and history: Open-Meteo, including ERA5 reanalysis. Creative Commons Attribution 4.0. One point inside each local government area. Accessed {escape(_day(data['access_date'], with_year=True))}.</li>
      <li>Air quality: Open-Meteo CAMS global air-quality forecast. Creative Commons Attribution 4.0. Fine particles and ozone.</li>
      <li>Who lives there: Australian Bureau of Statistics, Census 2021. Age, people living alone, and household income. Creative Commons Attribution 4.0. Boundaries from the 2021 statistical geography.</li>
      <li>A dangerous heat day on this page is a day of 35°C or hotter. A stricter health figure, used in the preparation notes when it occurs, is the Victorian Department of Health temperature level for that district: a hot day followed by a night that stays warm.</li>
      <li>Low income means a household living on less than $500 a week in 2021 dollars, including households with no income.</li>
      <li>This is not medical advice and it does not predict deaths. Temperatures are for one point in each area, not every town. Population figures are from 2021.</li>
    </ul>
  </footer>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const colours = {{1: "#f6e7c1", 2: "#f0b56a", 3: "#e07a3d", 4: "#c2410c", 5: "#7c2d12"}};
const map = L.map("map", {{scrollWheelZoom: false}}).setView([-36.8, 145.0], 6);
L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
  maxZoom: 12,
  attribution: "&copy; OpenStreetMap"
}}).addTo(map);
fetch("areas.geojson").then((response) => response.json()).then((areas) => {{
  const layer = L.geoJSON(areas, {{
    style: (feature) => ({{
      color: "#fffdf8",
      weight: 0.8,
      fillColor: colours[feature.properties.bin] || "#f6e7c1",
      fillOpacity: 0.85
    }}),
    onEachFeature: (feature, shape) => {{
      const props = feature.properties;
      shape.bindTooltip(
        "<strong>" + props.name + "</strong><br>" +
        props.older + " people aged 65 and over<br>" +
        "About " + props.summer + " days of 35°C in a typical summer<br>" +
        "Hottest day ahead: " + props.ahead + "°C"
      );
    }}
  }}).addTo(map);
  map.fitBounds(layer.getBounds(), {{padding: [12, 12]}});
}});
</script>
</body>
</html>
"""


def fortnight_note(data: dict) -> str:
    anomaly = data["anomaly_c_population_weighted"]
    if anomaly <= -0.3:
        relation = "below the usual line"
    elif anomaly >= 0.3:
        relation = "above the usual line"
    else:
        relation = "close to the usual line"
    return (
        "Daytime high for a typical Victorian, compared with the same dates across 2016–2025. "
        f"The forecast sits {relation} for this fortnight."
    )


def comparison_phrase(data: dict) -> str:
    anomaly = data["anomaly_c_population_weighted"]
    if anomaly <= -0.05:
        return "cooler than usual"
    if anomaly >= 0.05:
        return "warmer than usual"
    return "close to usual"


def _areas_geojson(data: dict) -> dict:
    boundaries = json.loads((SNAPSHOT / "lga_boundaries.geojson").read_text())
    scores = {row["lga_code"]: row for row in _priority_rows()}
    values = sorted(row["priority_score"] for row in scores.values())

    def bin_for(score: float) -> int:
        if not values:
            return 1
        rank = sum(1 for value in values if value <= score) / len(values)
        return min(5, max(1, int(rank * 5 + 0.0001) or 1))

    features = []
    for feature in boundaries["features"]:
        props = feature["properties"]
        code = str(props["lga_code_2021"])
        row = scores.get(code)
        if row is None:
            continue
        name = row["lga_name"].replace(" (Vic.)", "")
        features.append(
            {
                "type": "Feature",
                "geometry": feature["geometry"],
                "properties": {
                    "code": code,
                    "name": name,
                    "bin": bin_for(row["priority_score"]),
                    "older": f"{int(row['people_65_plus']):,}",
                    "summer": f"{row['avg_summer_very_hot_days']:.0f}",
                    "ahead": f"{row['forecast_max_c']:.0f}",
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _priority_rows() -> list[dict]:
    import duckdb

    frame = duckdb.execute(
        """
        select lga_code, lga_name, priority_score, people_65_plus,
               avg_summer_very_hot_days, forecast_max_c
        from read_parquet(?)
        """,
        [str(MARTS / "lga_priority.parquet")],
    ).df()
    return json.loads(frame.to_json(orient="records"))


def build_site() -> None:
    data = _load()
    story = _narrative(data)
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "index.html").write_text(_page(data, story))
    (SITE / "areas.geojson").write_text(json.dumps(_areas_geojson(data)))
    (SITE / "dashboard.json").write_text(json.dumps({"story": story, "headline": data}, indent=2) + "\n")
    (SITE / ".nojekyll").write_text("")
    print(f"wrote {SITE / 'index.html'}")


def main() -> None:
    build_site()


if __name__ == "__main__":
    main()
