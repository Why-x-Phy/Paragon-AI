from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import text

from app.models import (
    AlertItem,
    AnalysisInput,
    AnalysisResponse,
    CaseDetail,
    CaseSummary,
    FeatureItem,
    GateStatus,
    SimulationResult,
)
from app.services.db import session_scope
from app.services.settings import SETTINGS
from app.services.sim_math import estimate_fill_ratio


def save_raw_snapshot(source: str, symbol: str, payload: dict, data_degraded: bool, notes: list[str]) -> int:
    with session_scope() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO raw_snapshots(source, symbol, payload, data_degraded, notes)
                VALUES (:source, :symbol, :payload, :data_degraded, :notes)
                RETURNING id
                """
            ),
            {
                "source": source,
                "symbol": symbol,
                "payload": json.dumps(payload),
                "data_degraded": data_degraded,
                "notes": json.dumps(notes),
            },
        ).first()
    return int(row[0])


def _derive_alerts(response: AnalysisResponse, case_id: int) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if response.event_risk in {"high", "medium"}:
        alerts.append(
            {
                "case_id": case_id,
                "alert_type": "event_risk_mode",
                "severity": "high" if response.event_risk == "high" else "medium",
                "payload": {"event_risk": response.event_risk},
            }
        )
    if response.regime in {"expansion", "compression"}:
        alerts.append(
            {
                "case_id": case_id,
                "alert_type": "regime_shift_candidate",
                "severity": "medium",
                "payload": {"regime": response.regime, "confidence": response.regime_confidence},
            }
        )
    if response.total_score < 45:
        alerts.append(
            {
                "case_id": case_id,
                "alert_type": "no_trade_bias",
                "severity": "low",
                "payload": {"score": response.total_score},
            }
        )
    return alerts


def save_case(input_data: AnalysisInput, response: AnalysisResponse, subscores: dict[str, Any]) -> int:
    penalties = {
        "event_penalty": subscores["event_penalty"],
        "data_penalty": subscores["data_penalty"],
    }
    with session_scope() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO cases(symbol, timeframe_set, regime, regime_confidence, data_degraded, feature_version, model_version)
                VALUES (:symbol, :timeframe_set, :regime, :regime_confidence, :data_degraded, :feature_version, :model_version)
                RETURNING id
                """
            ),
            {
                "symbol": input_data.symbol,
                "timeframe_set": input_data.timeframe_set,
                "regime": response.regime,
                "regime_confidence": response.regime_confidence,
                "data_degraded": input_data.data_degraded,
                "feature_version": "v1",
                "model_version": "pipeline_v2",
            },
        ).first()
        case_id = int(row[0])

        for feature_key, feature_value in input_data.model_dump().items():
            conn.execute(
                text(
                    """
                    INSERT INTO features(case_id, feature_key, feature_value)
                    VALUES (:case_id, :feature_key, :feature_value)
                    """
                ),
                {
                    "case_id": case_id,
                    "feature_key": feature_key,
                    "feature_value": json.dumps(feature_value),
                },
            )

        for scenario in response.scenarios:
            conn.execute(
                text(
                    """
                    INSERT INTO scenarios(case_id, scenario_name, bias, probability, trigger_text, invalidation_text, targets, risk_notes, reason_codes)
                    VALUES (:case_id, :scenario_name, :bias, :probability, :trigger_text, :invalidation_text, :targets, :risk_notes, :reason_codes)
                    """
                ),
                {
                    "case_id": case_id,
                    "scenario_name": scenario.name,
                    "bias": scenario.bias,
                    "probability": scenario.probability,
                    "trigger_text": scenario.trigger,
                    "invalidation_text": scenario.invalidation,
                    "targets": json.dumps(scenario.targets),
                    "risk_notes": json.dumps(scenario.risk_notes),
                    "reason_codes": json.dumps(scenario.reason_codes),
                },
            )

        conn.execute(
            text(
                """
                INSERT INTO scores(case_id, total_score, bull_prob, bear_prob, subscores, penalties, reason_codes)
                VALUES (:case_id, :total_score, :bull_prob, :bear_prob, :subscores, :penalties, :reason_codes)
                """
            ),
            {
                "case_id": case_id,
                "total_score": response.total_score,
                "bull_prob": response.bull_prob,
                "bear_prob": response.bear_prob,
                "subscores": json.dumps(subscores),
                "penalties": json.dumps(penalties),
                "reason_codes": json.dumps(response.reason_codes),
            },
        )

        for alert in _derive_alerts(response, case_id):
            conn.execute(
                text(
                    """
                    INSERT INTO alerts(case_id, alert_type, severity, payload)
                    VALUES (:case_id, :alert_type, :severity, :payload)
                    """
                ),
                {
                    "case_id": alert["case_id"],
                    "alert_type": alert["alert_type"],
                    "severity": alert["severity"],
                    "payload": json.dumps(alert["payload"]),
                },
            )

    return case_id


def list_cases(limit: int = 50) -> list[CaseSummary]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT c.id, c.created_at, c.symbol, c.regime, s.total_score, s.bull_prob, s.bear_prob
                FROM cases c
                JOIN scores s ON s.case_id = c.id
                ORDER BY c.id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [
        CaseSummary(
            id=int(r.id),
            created_at=str(r.created_at),
            symbol=r.symbol,
            regime=r.regime,
            total_score=int(r.total_score),
            bull_prob=float(r.bull_prob),
            bear_prob=float(r.bear_prob),
        )
        for r in rows
    ]




def list_raw_snapshots(limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, source, symbol, payload, data_degraded, notes, created_at
                FROM raw_snapshots
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [
        {
            "id": int(r.id),
            "source": r.source,
            "symbol": r.symbol,
            "payload": json.loads(r.payload),
            "data_degraded": bool(r.data_degraded),
            "notes": json.loads(r.notes),
            "created_at": str(r.created_at),
        }
        for r in rows
    ]

def list_features(case_id: int, limit: int = 200) -> list[FeatureItem]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, case_id, feature_key, feature_value, created_at
                FROM features
                WHERE case_id = :case_id
                ORDER BY id ASC
                LIMIT :limit
                """
            ),
            {"case_id": case_id, "limit": limit},
        ).fetchall()
    return [
        FeatureItem(
            id=int(r.id),
            case_id=int(r.case_id),
            feature_key=r.feature_key,
            feature_value=r.feature_value,
            created_at=str(r.created_at),
        )
        for r in rows
    ]


def list_alerts(limit: int = 100) -> list[AlertItem]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, case_id, alert_type, severity, payload, created_at, acknowledged
                FROM alerts
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [
        AlertItem(
            id=int(r.id),
            case_id=int(r.case_id) if r.case_id is not None else None,
            alert_type=r.alert_type,
            severity=r.severity,
            payload=json.loads(r.payload),
            created_at=str(r.created_at),
            acknowledged=bool(r.acknowledged),
        )
        for r in rows
    ]


def acknowledge_alert(alert_id: int) -> bool:
    with session_scope() as conn:
        result = conn.execute(
            text("UPDATE alerts SET acknowledged = TRUE WHERE id = :alert_id"),
            {"alert_id": alert_id},
        )
    return result.rowcount > 0


def _deterministic_outcome_seed(case_id: int, horizon: str, scenario: str) -> int:
    raw = f"{case_id}:{horizon}:{scenario}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def simulate_case(case_id: int, horizon: str, chosen_scenario: str) -> SimulationResult:
    horizons = {"30m": 0.8, "1h": 1.1, "4h": 1.8, "1d": 2.6}
    if horizon not in horizons:
        raise ValueError("invalid_horizon")
    if chosen_scenario not in {"primary", "secondary", "no_trade"}:
        raise ValueError("invalid_scenario")

    with session_scope() as conn:
        exists = conn.execute(text("SELECT id FROM cases WHERE id = :id"), {"id": case_id}).first()
        if not exists:
            raise LookupError("case_not_found")

    seed = _deterministic_outcome_seed(case_id, horizon, chosen_scenario)
    signed = ((seed % 2001) - 1000) / 1000
    amplitude = horizons[horizon]

    if chosen_scenario == "primary":
        pnl = round(0.35 * amplitude + 0.5 * signed, 4)
    elif chosen_scenario == "secondary":
        pnl = round(-0.1 * amplitude + 0.6 * signed, 4)
    else:
        pnl = round(0.02 * signed, 4)

    mfe = round(max(pnl, 0) + 0.4 * amplitude, 4)
    mae = round(min(pnl, 0) - 0.35 * amplitude, 4)
    if pnl > 0.05:
        label = "win"
    elif pnl < -0.05:
        label = "loss"
    else:
        label = "flat"

    with session_scope() as conn:
        conn.execute(
            text(
                """
                INSERT INTO outcomes(case_id, chosen_scenario, horizon, pnl_pct, mfe_pct, mae_pct, outcome_label)
                VALUES (:case_id, :chosen_scenario, :horizon, :pnl_pct, :mfe_pct, :mae_pct, :outcome_label)
                """
            ),
            {
                "case_id": case_id,
                "chosen_scenario": chosen_scenario,
                "horizon": horizon,
                "pnl_pct": pnl,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "outcome_label": label,
            },
        )

    return SimulationResult(
        case_id=case_id,
        horizon=horizon,
        chosen_scenario=chosen_scenario,
        pnl_pct=pnl,
        mfe_pct=mfe,
        mae_pct=mae,
        outcome_label=label,
        fill_ratio=1.0,
        total_cost_pct=0.0,
    )




def simulate_case_realistic(
    case_id: int,
    horizon: str,
    chosen_scenario: str,
    spread_bps: float,
    expected_slippage_bps: float,
    fee_bps: float,
) -> SimulationResult:
    base = simulate_case(case_id=case_id, horizon=horizon, chosen_scenario=chosen_scenario)
    total_cost_pct = (spread_bps + expected_slippage_bps + fee_bps) / 10000.0

    fill_ratio = estimate_fill_ratio(spread_bps=spread_bps, expected_slippage_bps=expected_slippage_bps)

    gross_pnl = base.pnl_pct * fill_ratio
    pnl = round(gross_pnl - total_cost_pct, 4)
    mfe = round(max((base.mfe_pct * fill_ratio) - (spread_bps / 10000.0), 0.0), 4)
    mae = round((base.mae_pct * fill_ratio) - (expected_slippage_bps / 10000.0), 4)

    if pnl > 0.05:
        label = "win"
    elif pnl < -0.05:
        label = "loss"
    else:
        label = "flat"

    with session_scope() as conn:
        conn.execute(
            text(
                """
                INSERT INTO outcomes(case_id, chosen_scenario, horizon, pnl_pct, mfe_pct, mae_pct, outcome_label)
                VALUES (:case_id, :chosen_scenario, :horizon, :pnl_pct, :mfe_pct, :mae_pct, :outcome_label)
                """
            ),
            {
                "case_id": case_id,
                "chosen_scenario": f"{chosen_scenario}_realistic",
                "horizon": horizon,
                "pnl_pct": pnl,
                "mfe_pct": mfe,
                "mae_pct": mae,
                "outcome_label": label,
            },
        )

    return SimulationResult(
        case_id=case_id,
        horizon=horizon,
        chosen_scenario=chosen_scenario,
        pnl_pct=pnl,
        mfe_pct=mfe,
        mae_pct=mae,
        outcome_label=label,
        fill_ratio=fill_ratio,
        total_cost_pct=round(total_cost_pct, 4),
    )


def _save_risk_event(event_type: str, severity: str, payload: dict) -> int:
    with session_scope() as conn:
        row = conn.execute(
            text(
                """
                INSERT INTO risk_events(event_type, severity, payload)
                VALUES (:event_type, :severity, :payload)
                RETURNING id
                """
            ),
            {"event_type": event_type, "severity": severity, "payload": json.dumps(payload)},
        ).first()
    return int(row[0])


def evaluate_kill_switch(
    daily_loss_pct: float,
    consecutive_losses: int,
    api_error_rate: float,
    event_severity: int,
) -> dict:
    reasons: list[str] = []
    if daily_loss_pct <= -3.0:
        reasons.append("DAILY_LOSS_LIMIT")
    if consecutive_losses >= 5:
        reasons.append("CONSECUTIVE_LOSSES")
    if api_error_rate >= 0.15:
        reasons.append("API_ERROR_SPIKE")
    if event_severity >= 3:
        reasons.append("EVENT_SEVERITY_CRITICAL")

    triggered = len(reasons) > 0
    if triggered:
        _save_risk_event(
            event_type="kill_switch_trigger",
            severity="high",
            payload={
                "daily_loss_pct": daily_loss_pct,
                "consecutive_losses": consecutive_losses,
                "api_error_rate": api_error_rate,
                "event_severity": event_severity,
                "reason_codes": reasons,
            },
        )
    return {"triggered": triggered, "reason_codes": reasons}


def list_risk_events(limit: int = 100) -> list[dict[str, Any]]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, event_type, severity, payload, created_at
                FROM risk_events
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [
        {
            "id": int(r.id),
            "event_type": r.event_type,
            "severity": r.severity,
            "payload": json.loads(r.payload),
            "created_at": str(r.created_at),
        }
        for r in rows
    ]

def gate_status(min_sample: int | None = None) -> GateStatus:
    thresholds = SETTINGS.gate
    target_sample = min_sample if min_sample is not None else thresholds.min_sample

    with session_scope() as conn:
        rows = conn.execute(text("SELECT pnl_pct, outcome_label FROM outcomes ORDER BY id DESC LIMIT 500")).fetchall()

    sample = len(rows)
    if sample == 0:
        return GateStatus(
            execution_enabled=SETTINGS.execution_enabled,
            min_sample_met=False,
            profit_factor=0.0,
            max_drawdown_pct=0.0,
            winrate=0.0,
            sample_size=0,
            gate_passed=False,
        )

    pnl_values = [float(r.pnl_pct) for r in rows]
    gross_win = sum(p for p in pnl_values if p > 0)
    gross_loss = abs(sum(p for p in pnl_values if p < 0))
    profit_factor = round(gross_win / gross_loss, 3) if gross_loss > 0 else 9.999

    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnl_values:
        eq += p
        peak = max(peak, eq)
        max_dd = min(max_dd, eq - peak)

    wins = sum(1 for r in rows if r.outcome_label == "win")
    winrate = round(wins / sample, 3)
    max_drawdown_pct = round(abs(max_dd), 3)

    min_sample_met = sample >= target_sample
    gate_passed = (
        min_sample_met
        and profit_factor >= thresholds.min_profit_factor
        and max_drawdown_pct <= thresholds.max_drawdown_pct
        and winrate >= thresholds.min_winrate
    )

    return GateStatus(
        execution_enabled=SETTINGS.execution_enabled,
        min_sample_met=min_sample_met,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        winrate=winrate,
        sample_size=sample,
        gate_passed=gate_passed,
    )


def get_case(case_id: int) -> CaseDetail | None:
    with session_scope() as conn:
        header = conn.execute(
            text(
                """
                SELECT c.id, c.created_at, c.symbol, c.regime, s.total_score, s.bull_prob, s.bear_prob, c.timeframe_set, c.regime_confidence, c.data_degraded
                FROM cases c
                JOIN scores s ON s.case_id = c.id
                WHERE c.id = :case_id
                """
            ),
            {"case_id": case_id},
        ).first()
        if not header:
            return None

        scenario_rows = conn.execute(
            text("SELECT scenario_name, bias, probability, trigger_text, invalidation_text, targets, risk_notes, reason_codes FROM scenarios WHERE case_id = :case_id"),
            {"case_id": case_id},
        ).fetchall()

        reasons_row = conn.execute(text("SELECT reason_codes FROM scores WHERE case_id = :case_id"), {"case_id": case_id}).first()

    from app.models import AnalysisResponse, Scenario

    scenarios = [
        Scenario(
            name=r.scenario_name,
            bias=r.bias,
            probability=float(r.probability),
            trigger=r.trigger_text,
            invalidation=r.invalidation_text,
            targets=json.loads(r.targets),
            risk_notes=json.loads(r.risk_notes),
            reason_codes=json.loads(r.reason_codes),
        )
        for r in scenario_rows
    ]

    analysis = AnalysisResponse(
        regime=header.regime,
        regime_confidence=float(header.regime_confidence),
        macro_context="replay",
        patterns_structures=[],
        momentum_state="replay",
        vp_vwap_levels=[],
        liquidity_orderflow_zones=[],
        derivatives_liquidations=[],
        session_time_risk=[],
        event_risk="replay",
        scenarios=scenarios,
        total_score=int(header.total_score),
        bull_prob=float(header.bull_prob),
        bear_prob=float(header.bear_prob),
        reason_codes=json.loads(reasons_row.reason_codes),
        data_quality_flags=[f"DATA_DEGRADED={str(bool(header.data_degraded)).lower()}"],
    )

    summary = CaseSummary(
        id=int(header.id),
        created_at=str(header.created_at),
        symbol=header.symbol,
        regime=header.regime,
        total_score=int(header.total_score),
        bull_prob=float(header.bull_prob),
        bear_prob=float(header.bear_prob),
    )
    return CaseDetail(case=summary, analysis=analysis)


def system_metrics() -> dict[str, int | float]:
    with session_scope() as conn:
        c = conn.execute(text("SELECT COUNT(*) AS n FROM cases")).first()
        a = conn.execute(text("SELECT COUNT(*) AS n FROM alerts WHERE acknowledged = FALSE")).first()
        o = conn.execute(text("SELECT COUNT(*) AS n FROM outcomes")).first()
        r = conn.execute(text("SELECT COUNT(*) AS n FROM risk_events")).first()
    return {
        "cases_count": int(c.n if c else 0),
        "open_alerts_count": int(a.n if a else 0),
        "outcomes_count": int(o.n if o else 0),
        "risk_events_count": int(r.n if r else 0),
    }


def event_timeline(limit: int = 50) -> list[dict[str, Any]]:
    with session_scope() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, payload, created_at
                FROM raw_snapshots
                ORDER BY id DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()

    timeline: list[dict[str, Any]] = []
    for r in rows:
        payload = json.loads(r.payload)
        ev = payload.get("event", {}) if isinstance(payload, dict) else {}
        timeline.append(
            {
                "snapshot_id": int(r.id),
                "event_severity": int(ev.get("event_severity", 0)),
                "created_at": str(r.created_at),
            }
        )
    return timeline
