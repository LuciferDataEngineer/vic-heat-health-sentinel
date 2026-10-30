"""The Excess Heat Factor matches a hand-worked example."""

from vhhs.heat import excess_heat_factors, heatwave_category, is_dangerous, severe_threshold


def test_health_alert_uses_today_and_the_next_night():
    assert is_dangerous(temp_max=38, next_night_min=22, threshold=30)
    assert not is_dangerous(temp_max=38, next_night_min=18, threshold=30)


def test_excess_heat_factor_hand_calculation():
    # Thirty mild days, then three hot days. The first scored day is index 32.
    means = [20.0] * 30 + [30.0, 30.0, 30.0]
    factors = excess_heat_factors(means, t95=25.0)
    assert factors[31] is None
    # Three-day mean 30, prior 30-day mean 20, so EHF = (30-25) * max(1, 30-20) = 50.
    assert factors[32] == 50.0


def test_severe_needs_enough_positive_days():
    assert severe_threshold([1.0] * 10) is None
    level = severe_threshold([1.0] * 19 + [10.0])
    assert level is not None
    assert heatwave_category(10.0, level) in {"severe", "extreme", "low"}
