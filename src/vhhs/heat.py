"""Heat metrics shared by the warehouse SQL and the unit tests.

Dangerous heat day
    The Victorian health threshold: the average of today's maximum and the
    following night's minimum is at or above the district threshold
    (30, 32, or 34°C).

Excess Heat Factor
    The Bureau of Meteorology definition (Nairn and Fawcett). Daily mean
    temperature is the average of the maximum and the minimum. The three-day
    mean is compared with the 95th percentile of daily mean temperature at
    that location, and with the mean of the 30 days before those three days.

    EHI_sig = T3 - T95
    EHI_accl = T3 - T30
    EHF = EHI_sig * max(1, EHI_accl)

    A positive EHF is a low-intensity heatwave day. Severe is at or above the
    85th percentile of positive EHF values at that location. Extreme is at
    least three times that severe level.

The recent baseline is 2016–2025, not 1971–2000. A warmer baseline means we
do not treat the last decade's ordinary hot day as exceptional.
"""

from __future__ import annotations

import math


def daily_mean(temp_max: float, temp_min: float) -> float:
    return (temp_max + temp_min) / 2.0


def heat_health_mean(temp_max: float, next_night_min: float) -> float:
    return (temp_max + next_night_min) / 2.0


def is_dangerous(temp_max: float, next_night_min: float, threshold: float) -> bool:
    return heat_health_mean(temp_max, next_night_min) >= threshold


def percentile_linear(values: list[float], fraction: float) -> float:
    """Linear percentile, matching the common inclusive method used in tests.

    ``fraction`` is between 0 and 1. One value returns that value.
    """
    if not values:
        raise ValueError("percentile of an empty series")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def excess_heat_factors(daily_means: list[float], t95: float) -> list[float | None]:
    """EHF for each day. None until 33 days of history exist (3 + 30)."""
    result: list[float | None] = []
    for index in range(len(daily_means)):
        if index < 32:
            result.append(None)
            continue
        window = daily_means[index - 2 : index + 1]
        previous = daily_means[index - 32 : index - 2]
        if len(window) != 3 or len(previous) != 30:
            result.append(None)
            continue
        if any(value is None or math.isnan(value) for value in window + previous):
            result.append(None)
            continue
        three_day = sum(window) / 3.0
        prior_30 = sum(previous) / 30.0
        significance = three_day - t95
        acclimatisation = three_day - prior_30
        result.append(significance * max(1.0, acclimatisation))
    return result


def severe_threshold(ehf_values: list[float | None]) -> float | None:
    positive = [value for value in ehf_values if value is not None and value > 0]
    if len(positive) < 20:
        return None
    # statistics.quantiles is exclusive; the linear helper stays comparable
    # with a hand-checked example. n=20 is the floor used by the pipeline too.
    try:
        return percentile_linear(positive, 0.85)
    except ValueError:
        return None


def heatwave_category(ehf: float | None, severe: float | None) -> str | None:
    if ehf is None or ehf <= 0:
        return None
    if severe is None or severe <= 0:
        return "low"
    if ehf >= 3 * severe:
        return "extreme"
    if ehf >= severe:
        return "severe"
    return "low"


def rolling_mean(values: list[float], window: int) -> list[float | None]:
    """Trailing mean of ``window`` points, aligned to the last point."""
    output: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            output.append(None)
            continue
        chunk = values[index + 1 - window : index + 1]
        output.append(sum(chunk) / window)
    return output

