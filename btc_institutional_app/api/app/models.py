from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Literal


class Scenario(BaseModel):
    name: Literal["primary", "secondary", "no_trade"]
    bias: Literal["bull", "bear", "neutral"]
    probability: float = Field(ge=0.0, le=1.0)
    trigger: str
    invalidation: str
    targets: List[str] = Field(default_factory=list)
    risk_notes: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list, max_length=10)


class AnalysisResponse(BaseModel):
    regime: str
    regime_confidence: float = Field(ge=0.0, le=1.0)
    macro_context: str
    patterns_structures: List[str]
    momentum_state: str
    vp_vwap_levels: List[str]
    liquidity_orderflow_zones: List[str]
    derivatives_liquidations: List[str]
    session_time_risk: List[str]
    event_risk: str
    scenarios: List[Scenario]
    total_score: int = Field(ge=0, le=100)
    bull_prob: float = Field(ge=0.0, le=1.0)
    bear_prob: float = Field(ge=0.0, le=1.0)
    reason_codes: List[str]
    data_quality_flags: List[str]


class AnalysisInput(BaseModel):
    symbol: str = "BTCUSDT"
    timeframe_set: str = "1m,5m,15m,1h,4h,1d"
    price: float = Field(gt=0)
    ema20: float
    ema50: float
    ema200: float
    rsi: float = Field(ge=0, le=100)
    macd_hist: float
    bb_width: float = Field(ge=0)
    atr_pct: float = Field(ge=0)
    vol_zscore: float
    pattern_hints: List[str] = Field(default_factory=list)
    funding_rate: float = 0.0
    oi_change_pct: float = 0.0
    squeeze_up_prob: float = Field(default=0.5, ge=0, le=1)
    squeeze_down_prob: float = Field(default=0.5, ge=0, le=1)
    long_liq_usd_24h: float = 0.0
    short_liq_usd_24h: float = 0.0
    anchored_vwap_dist_bps: float = 0.0
    vp_balance: float = Field(default=0.0, ge=-1, le=1)
    absorption_score: float = Field(default=0.0, ge=0, le=1)
    sweep_risk_score: float = Field(default=0.0, ge=0, le=1)
    orderbook_imbalance: float = Field(default=0.0, ge=-1, le=1)
    depth_thinness: float = Field(default=0.0, ge=0, le=1)
    vp_value_acceptance: float = Field(default=0.0, ge=0, le=1)
    vwap_slope_bps: float = 0.0
    mtf_trend_score: float = Field(default=0.5, ge=0, le=1)
    mtf_volatility: float = Field(default=0.0, ge=0)
    mtf_alignment_ratio: float = Field(default=0.5, ge=0, le=1)
    calendar_coverage_score: float = Field(default=0.0, ge=0, le=1)
    macro_corr_ndx: float = Field(default=0.0, ge=-1, le=1)
    macro_corr_spx: float = Field(default=0.0, ge=-1, le=1)
    session: Literal["asia", "london", "newyork", "weekend"] = "london"
    event_severity: int = Field(default=0, ge=0, le=3)
    data_degraded: bool = False


class CaseSummary(BaseModel):
    id: int
    created_at: str
    symbol: str
    regime: str
    total_score: int
    bull_prob: float
    bear_prob: float


class CaseDetail(BaseModel):
    case: CaseSummary
    analysis: AnalysisResponse


class FeatureItem(BaseModel):
    id: int
    case_id: int
    feature_key: str
    feature_value: str
    created_at: str


class AlertItem(BaseModel):
    id: int
    case_id: int | None = None
    alert_type: str
    severity: str
    payload: dict
    created_at: str
    acknowledged: bool


class SimulationResult(BaseModel):
    case_id: int
    horizon: Literal["30m", "1h", "4h", "1d"]
    chosen_scenario: Literal["primary", "secondary", "no_trade"]
    pnl_pct: float
    mfe_pct: float
    mae_pct: float
    outcome_label: Literal["win", "loss", "flat"]
    fill_ratio: float = Field(default=1.0, ge=0.0, le=1.0)
    total_cost_pct: float = Field(default=0.0, ge=0.0)


class GateStatus(BaseModel):
    execution_enabled: bool
    min_sample_met: bool
    profit_factor: float
    max_drawdown_pct: float
    winrate: float
    sample_size: int
    gate_passed: bool


class SnapshotResponse(BaseModel):
    source: str
    data_degraded: bool
    notes: List[str] = Field(default_factory=list)
    snapshot: dict
    case_id: int | None = None


class ExecutionPrecheckRequest(BaseModel):
    symbol: str = "BTCUSDT"
    side: Literal["buy", "sell"]
    qty: float = Field(gt=0)
    spread_bps: float = Field(ge=0)
    expected_slippage_bps: float = Field(ge=0)
    volatility_spike: bool = False
    thin_liquidity: bool = False
    event_risk: Literal["low", "medium", "high"] = "low"
    data_degraded: bool = False


class ExecutionPrecheckResponse(BaseModel):
    allowed: bool
    reason_codes: List[str] = Field(default_factory=list)


class OrderRequest(BaseModel):
    symbol: str = "BTCUSDT"
    side: Literal["buy", "sell"]
    qty: float = Field(gt=0)
    order_type: Literal["market", "limit"] = "market"


class OrderResponse(BaseModel):
    accepted: bool
    reason_codes: List[str] = Field(default_factory=list)
    exchange_response: dict = Field(default_factory=dict)


class RawSnapshotItem(BaseModel):
    id: int
    source: str
    symbol: str
    payload: dict
    data_degraded: bool
    notes: List[str] = Field(default_factory=list)
    created_at: str


class ReconcileResponse(BaseModel):
    exchange: str
    open_orders_count: int
    fills_count: int
    position_count: int
    mismatches: List[str] = Field(default_factory=list)


class RealisticSimRequest(BaseModel):
    horizon: Literal["30m", "1h", "4h", "1d"] = "1h"
    chosen_scenario: Literal["primary", "secondary", "no_trade"] = "primary"
    spread_bps: float = Field(default=6.0, ge=0)
    expected_slippage_bps: float = Field(default=8.0, ge=0)
    fee_bps: float = Field(default=4.0, ge=0)


class RiskEventItem(BaseModel):
    id: int
    event_type: str
    severity: str
    payload: dict
    created_at: str


class KillSwitchRequest(BaseModel):
    daily_loss_pct: float = 0.0
    consecutive_losses: int = Field(default=0, ge=0)
    api_error_rate: float = Field(default=0.0, ge=0.0)
    event_severity: int = Field(default=0, ge=0, le=3)


class KillSwitchResponse(BaseModel):
    triggered: bool
    reason_codes: List[str] = Field(default_factory=list)


class ExecutionVerificationResponse(BaseModel):
    exchange: str
    configured: bool
    reachable: bool
    checks: List[str] = Field(default_factory=list)
    mismatches: List[str] = Field(default_factory=list)
