from __future__ import annotations

from dataclasses import dataclass
from typing import List

from app.models import AnalysisInput, AnalysisResponse, Scenario


@dataclass
class Subscores:
    regime: int
    structure: int
    momentum: int
    vp_vwap: int
    liquidity: int
    derivatives: int
    macro: int
    session: int
    event_penalty: int
    data_penalty: int


def classify_regime(i: AnalysisInput) -> tuple[str, float, list[str]]:
    if i.atr_pct < 0.008 and i.bb_width < 0.03:
        return "compression", 0.72, ["REGIME_COMPRESSION"]
    if i.vol_zscore > 1.2 and i.atr_pct > 0.012:
        return "expansion", 0.74, ["REGIME_EXPANSION"]
    if i.ema20 > i.ema50 > i.ema200:
        return "trend_up", 0.68, ["REGIME_TREND_UP"]
    if i.ema20 < i.ema50 < i.ema200:
        return "trend_down", 0.68, ["REGIME_TREND_DOWN"]
    return "range", 0.55, ["REGIME_RANGE"]



def _pattern_quality(i: AnalysisInput, hints: list[str]) -> tuple[int, list[str], list[str]]:
    normalized = sorted(set(h.lower().strip() for h in hints if h.strip()))
    quality_score = 0
    codes: list[str] = []

    asc = "ascending_triangle" in normalized
    wedge = "rising_wedge" in normalized

    if asc:
        quality_score += 4
        if i.ema20 > i.ema50 and i.rsi >= 50 and i.mtf_alignment_ratio >= 0.66:
            quality_score += 4
            codes.append("ASC_TRIANGLE_CONFIRMED_MTF")
        elif i.ema20 > i.ema50 and i.rsi >= 50:
            quality_score += 2
            codes.append("ASC_TRIANGLE_CONFIRMED")
        else:
            codes.append("ASC_TRIANGLE_WEAK_CONFIRMATION")

    if wedge:
        quality_score -= 1
        if i.rsi > 65 and i.macd_hist < 0 and i.vwap_slope_bps < 0:
            quality_score += 3
            codes.append("RISING_WEDGE_REVERSAL_CONFIRMED")
        elif i.rsi > 65 and i.macd_hist < 0:
            quality_score += 1
            codes.append("RISING_WEDGE_REVERSAL_RISK")
        else:
            codes.append("RISING_WEDGE_UNCONFIRMED")

    fakeout_risk = False
    if (asc or wedge) and i.bb_width < 0.018 and abs(i.macd_hist) < 0.08:
        fakeout_risk = True
        quality_score -= 2
        codes.append("FAKEOUT_RISK_ELEVATED")

    if not codes:
        codes.append("PATTERN_NEUTRAL")

    if fakeout_risk:
        normalized.append("fakeout_watch")

    return quality_score, codes, sorted(set(normalized))

def structure_engine(i: AnalysisInput) -> tuple[list[str], int, list[str]]:
    hints = i.pattern_hints or ["range_structure"]
    quality, quality_codes, normalized_hints = _pattern_quality(i, hints)

    score = 10 + quality
    score = max(4, min(18, score))

    codes = ["STRUCTURE_CONFIRMED"] if score >= 14 else ["STRUCTURE_WEAK"]
    codes.extend(quality_codes)
    return normalized_hints, score, codes


def momentum_engine(i: AnalysisInput) -> tuple[str, int, list[str]]:
    bullish = i.rsi > 52 and i.macd_hist > 0 and i.ema20 > i.ema50
    bearish = i.rsi < 48 and i.macd_hist < 0 and i.ema20 < i.ema50
    if bullish:
        return "bullish_alignment", 16, ["MOMENTUM_ALIGNED"]
    if bearish:
        return "bearish_alignment", 16, ["MOMENTUM_BEAR_ALIGNED"]
    return "mixed", 8, ["MOMENTUM_MIXED"]


def vp_vwap_engine(i: AnalysisInput) -> tuple[list[str], int, list[str]]:
    levels = [
        "POC_nearby",
        f"vp_balance={i.vp_balance:.2f}",
        f"anchored_vwap_dist_bps={i.anchored_vwap_dist_bps:.1f}",
        f"vp_acceptance={i.vp_value_acceptance:.2f}",
        f"vwap_slope_bps={i.vwap_slope_bps:.1f}",
    ]

    score = 8
    codes = ["VWAP_CONTEXT_OK"]
    if abs(i.anchored_vwap_dist_bps) < 25:
        score += 2
        codes.append("VWAP_MEAN_REVERSION_ZONE")
    elif i.anchored_vwap_dist_bps > 60:
        score += 1
        codes.append("VWAP_STRETCHED_UP")
    elif i.anchored_vwap_dist_bps < -60:
        score += 1
        codes.append("VWAP_STRETCHED_DOWN")

    if abs(i.vp_balance) > 0.25:
        score += 1
        codes.append("VP_IMBALANCE_DETECTED")
    if i.vp_value_acceptance < 0.35:
        score -= 1
        codes.append("VP_REJECTION_ZONE")
    if i.vwap_slope_bps > 25:
        score += 1
        codes.append("VWAP_SLOPE_UP")
    elif i.vwap_slope_bps < -25:
        score += 1
        codes.append("VWAP_SLOPE_DOWN")

    return levels, max(5, min(14, score)), codes


def liquidity_engine(i: AnalysisInput) -> tuple[list[str], int, list[str]]:
    zones = [
        "buy_side_liquidity_above",
        "sell_side_sweep_below",
        f"absorption={i.absorption_score:.2f}",
        f"sweep_risk={i.sweep_risk_score:.2f}",
        f"orderbook_imbalance={i.orderbook_imbalance:.2f}",
        f"depth_thinness={i.depth_thinness:.2f}",
    ]
    score = 9 if i.vol_zscore > 0 else 7
    codes = ["LIQUIDITY_MAP_ACTIVE"]

    if i.absorption_score > 0.65:
        score += 2
        codes.append("ABSORPTION_STRONG")
    if i.sweep_risk_score > 0.6:
        score -= 1
        codes.append("SWEEP_RISK_ELEVATED")
    if abs(i.orderbook_imbalance) > 0.3:
        score += 1
        codes.append("ORDERBOOK_IMBALANCE_SIGNAL")
    if i.depth_thinness > 0.6:
        score -= 1
        codes.append("DEPTH_THINNESS_HIGH")

    return zones, max(5, min(14, score)), codes


def derivatives_engine(i: AnalysisInput) -> tuple[list[str], int, list[str]]:
    liq_total = max(i.long_liq_usd_24h, 0.0) + max(i.short_liq_usd_24h, 0.0)
    liq_imbalance = 0.0
    if liq_total > 0:
        liq_imbalance = (i.short_liq_usd_24h - i.long_liq_usd_24h) / liq_total

    out = [
        f"squeeze_up_prob={i.squeeze_up_prob:.2f}",
        f"squeeze_down_prob={i.squeeze_down_prob:.2f}",
        f"long_liq_24h={i.long_liq_usd_24h:.0f}",
        f"short_liq_24h={i.short_liq_usd_24h:.0f}",
    ]

    crowded = abs(i.funding_rate) > 0.0008 or abs(i.oi_change_pct) > 5 or liq_total > 10_000_000
    imbalance_extreme = abs(liq_imbalance) > 0.35

    score = 12 if crowded or imbalance_extreme else 8
    codes = []
    if crowded:
        codes.append("DERIVATIVES_EXTREME")
    else:
        codes.append("DERIVATIVES_NORMAL")
    if imbalance_extreme:
        codes.append("LIQUIDATION_IMBALANCE")
    return out, score, codes


def macro_engine(i: AnalysisInput) -> tuple[str, int, list[str]]:
    support = (i.macro_corr_spx + i.macro_corr_ndx) / 2
    if support > 0.35:
        return "Macro supportive risk-on", 9, ["MACRO_SUPPORTIVE"]
    if support < -0.35:
        return "Macro opposing risk-off", 3, ["MACRO_OPPOSE"]
    return "Macro neutral", 6, ["MACRO_NEUTRAL"]


def session_engine(i: AnalysisInput) -> tuple[list[str], int, list[str]]:
    flags = [f"session={i.session}"]
    if i.session == "newyork":
        flags.append("ny_open_spike_risk")
        return flags, 6, ["SESSION_VOLATILE"]
    if i.session == "weekend":
        flags.append("thin_liquidity_penalty")
        return flags, 4, ["SESSION_WEEKEND"]
    return flags, 8, ["SESSION_STABLE"]


def event_penalty(i: AnalysisInput) -> tuple[str, int, list[str]]:
    if i.calendar_coverage_score < 0.25:
        return "medium", 10, ["EVENT_CALENDAR_LOW_COVERAGE"]
    if i.event_severity >= 2:
        return "high", 18, ["EVENT_RISK_MODE"]
    if i.event_severity == 1:
        return "medium", 8, ["EVENT_PROXIMITY"]
    return "low", 0, ["EVENT_CLEAR"]


def build_scenarios(i: AnalysisInput, bull_prob: float, bear_prob: float, reasons: List[str]) -> list[Scenario]:
    primary_bias = "bull" if bull_prob >= bear_prob else "bear"
    secondary_bias = "bear" if primary_bias == "bull" else "bull"
    return [
        Scenario(
            name="primary",
            bias=primary_bias,
            probability=round(max(bull_prob, bear_prob), 2),
            trigger="Breakout confirmation with volume + momentum follow-through",
            invalidation="Loss of structure + reclaim failure",
            targets=["T1=local HVN", "T2=liquidation magnet"],
            risk_notes=["Respect event-risk mode and session spikes"],
            reason_codes=reasons[:5],
        ),
        Scenario(
            name="secondary",
            bias=secondary_bias,
            probability=round(min(bull_prob, bear_prob), 2),
            trigger="Fakeout and return inside value area",
            invalidation="Impulse continuation in primary direction",
            targets=["POC retest", "opposite liquidity sweep"],
            risk_notes=["Crowded positioning can accelerate reversal"],
            reason_codes=["FAKEOUT_PATH", "RISK_MANAGEMENT"],
        ),
        Scenario(
            name="no_trade",
            bias="neutral",
            probability=round(max(0.05, 1 - bull_prob - bear_prob), 2),
            trigger="Edge below threshold or event risk too high",
            invalidation="Data quality recovers + clean setup appears",
            targets=[],
            risk_notes=["No-trade is valid under low edge"],
            reason_codes=["NO_TRADE_VALID"],
        ),
    ]


def run_pipeline(i: AnalysisInput) -> tuple[AnalysisResponse, Subscores]:
    regime, regime_conf, r_codes = classify_regime(i)
    patterns, s_score, s_codes = structure_engine(i)
    momentum, m_score, m_codes = momentum_engine(i)
    vp_lvls, vp_score, vp_codes = vp_vwap_engine(i)
    liq, liq_score, liq_codes = liquidity_engine(i)
    drv, d_score, d_codes = derivatives_engine(i)
    macro, macro_score, macro_codes = macro_engine(i)
    session_flags, session_score, session_codes = session_engine(i)
    event_state, e_penalty, event_codes = event_penalty(i)

    regime_score = int(regime_conf * 20)
    data_penalty = 10 if i.data_degraded else 0

    total = regime_score + s_score + m_score + vp_score + liq_score + d_score + macro_score + session_score - e_penalty - data_penalty
    total = max(0, min(100, total))

    bull_prob = max(0.05, min(0.9, (total / 100) * (1.0 if momentum != "bearish_alignment" else 0.6)))
    bear_prob = max(0.05, min(0.9, (1 - bull_prob) * (1.0 if momentum == "bearish_alignment" else 0.7)))

    all_codes = r_codes + s_codes + m_codes + vp_codes + liq_codes + d_codes + macro_codes + session_codes + event_codes
    reasons = all_codes[:10]
    scenarios = build_scenarios(i, bull_prob, bear_prob, reasons)

    response = AnalysisResponse(
        regime=regime,
        regime_confidence=round(regime_conf, 2),
        macro_context=macro,
        patterns_structures=patterns,
        momentum_state=momentum,
        vp_vwap_levels=vp_lvls,
        liquidity_orderflow_zones=liq,
        derivatives_liquidations=drv,
        session_time_risk=session_flags,
        event_risk=event_state,
        scenarios=scenarios,
        total_score=total,
        bull_prob=round(bull_prob, 2),
        bear_prob=round(bear_prob, 2),
        reason_codes=reasons,
        data_quality_flags=[f"DATA_DEGRADED={str(i.data_degraded).lower()}"],
    )

    scores = Subscores(
        regime=regime_score,
        structure=s_score,
        momentum=m_score,
        vp_vwap=vp_score,
        liquidity=liq_score,
        derivatives=d_score,
        macro=macro_score,
        session=session_score,
        event_penalty=e_penalty,
        data_penalty=data_penalty,
    )
    return response, scores
