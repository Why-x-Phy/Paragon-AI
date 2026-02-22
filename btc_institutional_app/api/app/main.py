from __future__ import annotations

from dataclasses import asdict
import json
import time

from fastapi import FastAPI, Header, HTTPException, Request

from app.engines.pipeline import run_pipeline
from app.models import (
    AlertItem,
    AnalysisInput,
    AnalysisResponse,
    CaseDetail,
    CaseSummary,
    ExecutionPrecheckRequest,
    ExecutionPrecheckResponse,
    FeatureItem,
    GateStatus,
    OrderRequest,
    OrderResponse,
    ReconcileResponse,
    ExecutionVerificationResponse,
    RealisticSimRequest,
    RiskEventItem,
    KillSwitchRequest,
    KillSwitchResponse,
    SimulationResult,
    SnapshotResponse,
    RawSnapshotItem,
)
from app.services.cases import (
    acknowledge_alert,
    gate_status,
    get_case,
    list_alerts,
    list_cases,
    list_features,
    list_raw_snapshots,
    list_risk_events,
    system_metrics,
    event_timeline,
    save_case,
    save_raw_snapshot,
    simulate_case,
    simulate_case_realistic,
    evaluate_kill_switch,
)
from app.services.db import init_db
from app.services.execution import build_exchange_client, pre_trade_check, reconcile_state, reconciliation_loop, verify_exchange_connectivity
from app.services.ingestion import analysis_input_from_snapshot, data_quality_flags, normalize_payload
from app.services.providers import (
    fetch_derivatives_context,
    fetch_event_risk_context,
    fetch_macro_context,
    fetch_market_snapshot,
    fetch_mtf_candle_features,
    fetch_microstructure_context,
)
from app.services.settings import SETTINGS

app = FastAPI(title="BTC Institutional Analysis API", version="0.7.0")
client = build_exchange_client()


def _require_write_token(x_write_token: str | None = Header(default=None)) -> None:
    if not SETTINGS.write_token:
        return
    if x_write_token != SETTINGS.write_token:
        raise HTTPException(status_code=401, detail="invalid_write_token")



@app.middleware("http")
async def request_logger(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    log_payload = {
        "path": request.url.path,
        "method": request.method,
        "status": response.status_code,
        "latency_ms": round((time.time()-t0)*1000, 2),
    }
    print(json.dumps(log_payload, ensure_ascii=False))
    return response


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/v1/health")
def health() -> dict:
    return {
        "status": "ok",
        "execution_enabled": SETTINGS.execution_enabled,
        "phase": "analysis_paper",
    }


@app.get("/v1/health/deep")
def health_deep() -> dict:
    metrics = system_metrics()
    return {
        "status": "ok",
        "execution_enabled": SETTINGS.execution_enabled,
        "metrics": metrics,
    }


@app.get("/v1/metrics")
def metrics() -> dict:
    return system_metrics()


@app.get("/v1/timeline/events")
def timeline_events(limit: int = 50) -> list[dict]:
    return event_timeline(limit=max(1, min(limit, 500)))

@app.post("/v1/ingestion/snapshot", response_model=SnapshotResponse)
def ingest_snapshot(symbol: str = "BTCUSDT", run_analysis: bool = True, x_write_token: str | None = Header(default=None)) -> SnapshotResponse:
    _require_write_token(x_write_token)
    provider = fetch_market_snapshot(symbol=symbol)
    macro = fetch_macro_context()
    derivatives = fetch_derivatives_context()
    event_ctx = fetch_event_risk_context()
    mtf = fetch_mtf_candle_features(symbol=symbol)
    micro = fetch_microstructure_context(symbol=symbol)

    degraded = provider.degraded or macro.degraded or derivatives.degraded or event_ctx.degraded or mtf.degraded or micro.degraded
    merged_notes = provider.notes + macro.notes + derivatives.notes + event_ctx.notes + mtf.notes + micro.notes
    merged_payload = {
        "market": provider.payload,
        "macro": macro.payload,
        "derivatives": derivatives.payload,
        "event": event_ctx.payload,
        "mtf": mtf.payload,
        "microstructure": micro.payload,
    }

    snapshot_id = save_raw_snapshot(
        source=f"{provider.source}+{macro.source}+{derivatives.source}+{event_ctx.source}+{mtf.source}+{micro.source}",
        symbol=symbol,
        payload=merged_payload,
        data_degraded=degraded,
        notes=merged_notes,
    )

    case_id = None
    if run_analysis:
        analysis_input = analysis_input_from_snapshot(
            provider.payload,
            degraded=degraded,
            macro=macro.payload,
            derivatives=derivatives.payload,
            event_ctx=event_ctx.payload,
            mtf=mtf.payload,
            micro=micro.payload,
        )
        normalized = normalize_payload(analysis_input)
        response, subscores = run_pipeline(normalized)
        response.data_quality_flags = data_quality_flags(normalized) + [f"RAW_SNAPSHOT_ID={snapshot_id}"]
        case_id = save_case(normalized, response, asdict(subscores))

    return SnapshotResponse(
        source=f"{provider.source}|{macro.source}|{derivatives.source}|{event_ctx.source}|{mtf.source}|{micro.source}",
        data_degraded=degraded,
        notes=merged_notes,
        snapshot=merged_payload,
        case_id=case_id,
    )


@app.post("/v1/analysis/run", response_model=AnalysisResponse)
def run_analysis(payload: AnalysisInput, x_write_token: str | None = Header(default=None)) -> AnalysisResponse:
    _require_write_token(x_write_token)
    normalized = normalize_payload(payload)
    response, subscores = run_pipeline(normalized)
    response.data_quality_flags = data_quality_flags(normalized)
    save_case(normalized, response, asdict(subscores))
    return response


@app.post("/v1/execution/precheck", response_model=ExecutionPrecheckResponse)
def execution_precheck(payload: ExecutionPrecheckRequest, x_write_token: str | None = Header(default=None)) -> ExecutionPrecheckResponse:
    _require_write_token(x_write_token)
    check = pre_trade_check(
        spread_bps=payload.spread_bps,
        expected_slippage_bps=payload.expected_slippage_bps,
        volatility_spike=payload.volatility_spike,
        thin_liquidity=payload.thin_liquidity,
        event_risk=payload.event_risk,
        data_degraded=payload.data_degraded,
    )
    return ExecutionPrecheckResponse(allowed=check.allowed, reason_codes=check.reason_codes)


@app.post("/v1/execution/order", response_model=OrderResponse)
def execution_order(payload: OrderRequest, x_write_token: str | None = Header(default=None)) -> OrderResponse:
    _require_write_token(x_write_token)
    check = pre_trade_check(
        spread_bps=0,
        expected_slippage_bps=0,
        volatility_spike=False,
        thin_liquidity=False,
        event_risk="low",
        data_degraded=False,
    )
    if not check.allowed:
        return OrderResponse(accepted=False, reason_codes=check.reason_codes, exchange_response={})

    exchange_resp = client.create_order(
        symbol=payload.symbol,
        side=payload.side,
        qty=payload.qty,
        order_type=payload.order_type,
    )
    accepted = bool(exchange_resp.get("accepted", False))
    return OrderResponse(
        accepted=accepted,
        reason_codes=[] if accepted else [exchange_resp.get("reason", "ORDER_REJECTED")],
        exchange_response=exchange_resp,
    )


@app.get("/v1/execution/verify", response_model=ExecutionVerificationResponse)
def execution_verify(symbol: str = "BTCUSDT") -> ExecutionVerificationResponse:
    result = verify_exchange_connectivity(client, symbol=symbol)
    return ExecutionVerificationResponse(
        exchange=result.exchange,
        configured=result.configured,
        reachable=result.reachable,
        checks=result.checks,
        mismatches=result.mismatches,
    )


@app.get("/v1/execution/reconcile", response_model=ReconcileResponse)
def execution_reconcile(symbol: str = "BTCUSDT", cycles: int = 1) -> ReconcileResponse:
    safe_cycles = max(1, min(cycles, 10))
    if safe_cycles > 1:
        result = reconciliation_loop(client, symbol=symbol, cycles=safe_cycles, pause_s=0.0)
    else:
        result = reconcile_state(client, symbol=symbol)
    return ReconcileResponse(
        exchange=result.exchange,
        open_orders_count=result.open_orders_count,
        fills_count=result.fills_count,
        position_count=result.position_count,
        mismatches=result.mismatches,
    )

@app.get("/v1/raw_snapshots", response_model=list[RawSnapshotItem])
def raw_snapshots(limit: int = 100) -> list[RawSnapshotItem]:
    rows = list_raw_snapshots(limit=max(1, min(limit, 500)))
    return [RawSnapshotItem(**r) for r in rows]

@app.get("/v1/cases", response_model=list[CaseSummary])
def history(limit: int = 50) -> list[CaseSummary]:
    return list_cases(limit=max(1, min(limit, 200)))


@app.get("/v1/cases/{case_id}", response_model=CaseDetail)
def replay(case_id: int) -> CaseDetail:
    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail="case_not_found")
    return case


@app.get("/v1/cases/{case_id}/features", response_model=list[FeatureItem])
def case_features(case_id: int, limit: int = 200) -> list[FeatureItem]:
    return list_features(case_id=case_id, limit=max(1, min(limit, 500)))


@app.get("/v1/alerts", response_model=list[AlertItem])
def alerts(limit: int = 100) -> list[AlertItem]:
    return list_alerts(limit=max(1, min(limit, 200)))


@app.post("/v1/alerts/{alert_id}/ack")
def ack_alert(alert_id: int, x_write_token: str | None = Header(default=None)) -> dict:
    _require_write_token(x_write_token)
    updated = acknowledge_alert(alert_id)
    if not updated:
        raise HTTPException(status_code=404, detail="alert_not_found")
    return {"acknowledged": True, "alert_id": alert_id}


@app.post("/v1/cases/{case_id}/simulate", response_model=SimulationResult)
def simulate(case_id: int, horizon: str = "1h", chosen_scenario: str = "primary", x_write_token: str | None = Header(default=None)) -> SimulationResult:
    _require_write_token(x_write_token)
    try:
        return simulate_case(case_id=case_id, horizon=horizon, chosen_scenario=chosen_scenario)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/cases/{case_id}/simulate_realistic", response_model=SimulationResult)
def simulate_realistic(case_id: int, payload: RealisticSimRequest, x_write_token: str | None = Header(default=None)) -> SimulationResult:
    _require_write_token(x_write_token)
    try:
        return simulate_case_realistic(
            case_id=case_id,
            horizon=payload.horizon,
            chosen_scenario=payload.chosen_scenario,
            spread_bps=payload.spread_bps,
            expected_slippage_bps=payload.expected_slippage_bps,
            fee_bps=payload.fee_bps,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/v1/risk/kill_switch/check", response_model=KillSwitchResponse)
def kill_switch_check(payload: KillSwitchRequest, x_write_token: str | None = Header(default=None)) -> KillSwitchResponse:
    _require_write_token(x_write_token)
    out = evaluate_kill_switch(
        daily_loss_pct=payload.daily_loss_pct,
        consecutive_losses=payload.consecutive_losses,
        api_error_rate=payload.api_error_rate,
        event_severity=payload.event_severity,
    )
    return KillSwitchResponse(triggered=out["triggered"], reason_codes=out["reason_codes"])


@app.get("/v1/risk/events", response_model=list[RiskEventItem])
def risk_events(limit: int = 100) -> list[RiskEventItem]:
    rows = list_risk_events(limit=max(1, min(limit, 500)))
    return [RiskEventItem(**r) for r in rows]

@app.get("/v1/gates/status", response_model=GateStatus)
def gates(min_sample: int | None = None) -> GateStatus:
    bounded = None if min_sample is None else max(1, min(min_sample, 5000))
    return gate_status(min_sample=bounded)
