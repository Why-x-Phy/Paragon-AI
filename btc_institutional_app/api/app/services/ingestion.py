from __future__ import annotations

from app.models import AnalysisInput


def normalize_payload(payload: AnalysisInput) -> AnalysisInput:
    hints = [h.lower().strip() for h in payload.pattern_hints if h.strip()]
    unique_hints = sorted(set(hints))
    return payload.model_copy(
        update={
            "pattern_hints": unique_hints,
            "timeframe_set": payload.timeframe_set.replace(" ", ""),
        }
    )


def data_quality_flags(payload: AnalysisInput) -> list[str]:
    flags = [f"DATA_DEGRADED={str(payload.data_degraded).lower()}"]
    if payload.event_severity >= 2:
        flags.append("EVENT_RISK_MODE=true")
    if payload.bb_width < 0.015:
        flags.append("LOW_VOL_COMPRESSION=true")
    if payload.vol_zscore > 2.5:
        flags.append("VOL_SPIKE=true")
    return flags


def analysis_input_from_snapshot(
    snapshot: dict,
    degraded: bool = False,
    macro: dict | None = None,
    derivatives: dict | None = None,
    event_ctx: dict | None = None,
    mtf: dict | None = None,
    micro: dict | None = None,
) -> AnalysisInput:
    price = float(snapshot.get("price") or 0.0)
    if price <= 0:
        raise ValueError("invalid_snapshot_price")

    high = float(snapshot.get("high") or price * 1.005)
    low = float(snapshot.get("low") or price * 0.995)
    open_px = float(snapshot.get("open") or price)
    spread = max(high - low, 1e-6)

    macro = macro or {}
    derivatives = derivatives or {}
    event_ctx = event_ctx or {}
    mtf = mtf or {}
    micro = micro or {}

    rsi = 50 + ((price - open_px) / spread) * 10
    rsi = max(20, min(80, rsi))

    hints = ["range_structure"]
    mtf_trend_score = float(mtf.get("mtf_trend_score", 0.5))
    mtf_alignment_ratio = float(mtf.get("mtf_alignment_ratio", 0.5))
    if mtf_trend_score > 0.6 and mtf_alignment_ratio >= 0.66:
        hints.append("mtf_trend_aligned")
    if float(micro.get("vp_value_acceptance", 0.0)) < 0.35:
        hints.append("vp_rejection_zone")

    vol_z = 1.0 if float(snapshot.get("volume", 0.0)) > 0 else 0.0
    vol_z = min(3.5, vol_z + float(mtf.get("mtf_volatility", 0.0)) * 1000)

    return AnalysisInput(
        symbol="BTCUSDT",
        timeframe_set="1m,5m,15m,1h,4h,1d",
        price=price,
        ema20=price * 0.998,
        ema50=price * 0.994,
        ema200=price * 0.97,
        rsi=rsi,
        macd_hist=(price - open_px) / max(open_px, 1.0) * 100,
        bb_width=spread / max(price, 1.0),
        atr_pct=spread / max(price, 1.0),
        vol_zscore=vol_z,
        pattern_hints=hints,
        funding_rate=float(derivatives.get("funding_rate", 0.0)),
        oi_change_pct=float(derivatives.get("oi_change_pct", 0.0)),
        squeeze_up_prob=float(derivatives.get("squeeze_up_prob", 0.55)),
        squeeze_down_prob=float(derivatives.get("squeeze_down_prob", 0.45)),
        long_liq_usd_24h=float(derivatives.get("long_liq_usd_24h", 0.0)),
        short_liq_usd_24h=float(derivatives.get("short_liq_usd_24h", 0.0)),
        anchored_vwap_dist_bps=float(micro.get("anchored_vwap_dist_bps", 0.0)),
        vp_balance=float(micro.get("vp_balance", 0.0)),
        absorption_score=float(micro.get("absorption_score", 0.0)),
        sweep_risk_score=float(micro.get("sweep_risk_score", 0.0)),
        orderbook_imbalance=float(micro.get("orderbook_imbalance", 0.0)),
        depth_thinness=float(micro.get("depth_thinness", 0.0)),
        vp_value_acceptance=float(micro.get("vp_value_acceptance", 0.0)),
        vwap_slope_bps=float(micro.get("vwap_slope_bps", 0.0)),
        mtf_trend_score=mtf_trend_score,
        mtf_volatility=float(mtf.get("mtf_volatility", 0.0)),
        mtf_alignment_ratio=mtf_alignment_ratio,
        calendar_coverage_score=float(event_ctx.get("calendar_coverage_score", 0.0)),
        macro_corr_ndx=float(macro.get("macro_corr_ndx", 0.0)),
        macro_corr_spx=float(macro.get("macro_corr_spx", 0.0)),
        session=str(micro.get("session", "london")),
        event_severity=int(event_ctx.get("event_severity", 0)),
        data_degraded=degraded,
    )
