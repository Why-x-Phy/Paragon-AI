from app.services.sim_math import estimate_fill_ratio


def test_estimate_fill_ratio_stays_full_when_costs_low():
    assert estimate_fill_ratio(spread_bps=4.0, expected_slippage_bps=6.0) == 1.0


def test_estimate_fill_ratio_reduces_with_stress_inputs():
    ratio = estimate_fill_ratio(spread_bps=25.0, expected_slippage_bps=30.0)
    assert 0.35 <= ratio < 1.0


def test_estimate_fill_ratio_has_floor():
    assert estimate_fill_ratio(spread_bps=1000.0, expected_slippage_bps=1000.0) == 0.35
