"""Victorian forecast districts and heat-health temperature thresholds.

The thresholds are the daily mean temperatures (today's maximum and the
following night's minimum, averaged) at which the Victorian Department of
Health says heat illness rises sharply. They were published for the state's
heat-health alert system and are still the figures councils use in heatwave
plans.

Source: Department of Health, "Heat health warning", health.vic.gov.au,
accessed 31 October 2026. Local government areas are those listed on that
page. Yarriambiack Shire straddles the Mallee/Wimmera fence; the whole shire
is given the lower Wimmera threshold so the southern half is not missed.
Areas that are not a council (unincorporated land, alpine resorts) fall back
to a latitude band and are flagged as such in the output.
"""

from __future__ import annotations

# Normalised council name -> (district, threshold °C).
DISTRICTS: dict[str, tuple[str, float]] = {
    # Mallee, 34°C
    "buloke": ("Mallee", 34.0),
    "gannawarra": ("Mallee", 34.0),
    "mildura": ("Mallee", 34.0),
    "swan hill": ("Mallee", 34.0),
    # Wimmera, 32°C
    "hindmarsh": ("Wimmera", 32.0),
    "horsham": ("Wimmera", 32.0),
    "northern grampians": ("Wimmera", 32.0),
    "west wimmera": ("Wimmera", 32.0),
    "yarriambiack": ("Wimmera", 32.0),
    # Northern Country, 32°C
    "campaspe": ("Northern Country", 32.0),
    "greater bendigo": ("Northern Country", 32.0),
    "greater shepparton": ("Northern Country", 32.0),
    "loddon": ("Northern Country", 32.0),
    "moira": ("Northern Country", 32.0),
    "strathbogie": ("Northern Country", 32.0),
    # North East, 32°C
    "alpine": ("North East", 32.0),
    "benalla": ("North East", 32.0),
    "indigo": ("North East", 32.0),
    "mansfield": ("North East", 32.0),
    "towong": ("North East", 32.0),
    "wangaratta": ("North East", 32.0),
    "wodonga": ("North East", 32.0),
    # North Central, 30°C
    "central goldfields": ("North Central", 30.0),
    "mitchell": ("North Central", 30.0),
    "mount alexander": ("North Central", 30.0),
    "murrindindi": ("North Central", 30.0),
    # East Gippsland, 30°C
    "east gippsland": ("East Gippsland", 30.0),
    # South West, 30°C
    "ararat": ("South West", 30.0),
    "colac otway": ("South West", 30.0),
    "corangamite": ("South West", 30.0),
    "glenelg": ("South West", 30.0),
    "moyne": ("South West", 30.0),
    "pyrenees": ("South West", 30.0),
    "southern grampians": ("South West", 30.0),
    "warrnambool": ("South West", 30.0),
    # West and South Gippsland, 30°C
    "baw baw": ("West and South Gippsland", 30.0),
    "latrobe": ("West and South Gippsland", 30.0),
    "south gippsland": ("West and South Gippsland", 30.0),
    "wellington": ("West and South Gippsland", 30.0),
    # Central, 30°C
    "ballarat": ("Central", 30.0),
    "banyule": ("Central", 30.0),
    "bass coast": ("Central", 30.0),
    "bayside": ("Central", 30.0),
    "boroondara": ("Central", 30.0),
    "brimbank": ("Central", 30.0),
    "cardinia": ("Central", 30.0),
    "casey": ("Central", 30.0),
    "darebin": ("Central", 30.0),
    "frankston": ("Central", 30.0),
    "glen eira": ("Central", 30.0),
    "golden plains": ("Central", 30.0),
    "greater dandenong": ("Central", 30.0),
    "greater geelong": ("Central", 30.0),
    "hepburn": ("Central", 30.0),
    "hobsons bay": ("Central", 30.0),
    "hume": ("Central", 30.0),
    "kingston": ("Central", 30.0),
    "knox": ("Central", 30.0),
    "macedon ranges": ("Central", 30.0),
    "manningham": ("Central", 30.0),
    "maribyrnong": ("Central", 30.0),
    "maroondah": ("Central", 30.0),
    "melbourne": ("Central", 30.0),
    "melton": ("Central", 30.0),
    "merri bek": ("Central", 30.0),
    "monash": ("Central", 30.0),
    "moonee valley": ("Central", 30.0),
    "moorabool": ("Central", 30.0),
    "mornington peninsula": ("Central", 30.0),
    "nillumbik": ("Central", 30.0),
    "port phillip": ("Central", 30.0),
    "queenscliffe": ("Central", 30.0),
    "stonnington": ("Central", 30.0),
    "surf coast": ("Central", 30.0),
    "whitehorse": ("Central", 30.0),
    "whittlesea": ("Central", 30.0),
    "wyndham": ("Central", 30.0),
    "yarra": ("Central", 30.0),
    "yarra ranges": ("Central", 30.0),
    "french island": ("Central", 30.0),
}

THRESHOLD_SOURCE = "https://www.health.vic.gov.au/environmental-health/heat-health-warning"


def normalise_lga_name(name: str) -> str:
    text = name.lower().replace("’", "'").replace("-", " ")
    text = text.replace("(vic.)", " ").replace("(vic)", " ")
    for token in (" rural city", " city", " shire", " borough"):
        text = text.replace(token, "")
    text = text.replace(" of ", " ")
    text = " ".join(text.split())
    # Moreland was renamed Merri-bek in 2022. The 2021 boundaries still say Moreland.
    if text == "moreland":
        return "merri bek"
    return text


def district_for(name: str, latitude: float) -> tuple[str, float, str]:
    """Return (district, threshold celsius, how the threshold was chosen)."""
    key = normalise_lga_name(name)
    if key in DISTRICTS:
        district, threshold = DISTRICTS[key]
        return district, threshold, "health.vic"
    # Unincorporated land and resorts are not in the council list.
    if latitude > -35.2:
        return "Mallee", 34.0, "latitude-fallback"
    if latitude > -36.4:
        return "Northern Country", 32.0, "latitude-fallback"
    return "Central", 30.0, "latitude-fallback"
