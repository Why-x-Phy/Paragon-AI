from __future__ import annotations


def estimate_fill_ratio(spread_bps: float, expected_slippage_bps: float) -> float:
    fill_ratio = 1.0
    if expected_slippage_bps > 12:
        fill_ratio -= min(0.45, (expected_slippage_bps - 12) / 100.0)
    if spread_bps > 15:
        fill_ratio -= min(0.25, (spread_bps - 15) / 120.0)
    return round(max(0.35, min(fill_ratio, 1.0)), 3)
