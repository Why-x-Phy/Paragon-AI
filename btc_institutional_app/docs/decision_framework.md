# Institutional Decision Framework

## Non-negotiables

- Explainability first (`reason_codes`).
- Probabilistic outputs (no deterministic signal claims).
- Regime-first strategy selection.
- No-trade is a valid and explicit scenario.
- Full reproducibility of every case.

## Minimum confirmation rule

Bias is constructed from:

- Regime fit
- Structure
- Momentum
- Context engines (VP/VWAP, Liquidity, Derivatives, Macro, Session)
- Minus penalties (Event risk + Data quality)

## Current scoring model

`total_score = sum(subscores) - event_penalty - data_penalty`

Subscores currently include:

- regime
- structure
- momentum
- vp_vwap
- liquidity
- derivatives
- macro
- session

Penalties:

- `event_penalty` (event severity proximity)
- `data_penalty` (degraded input)

Outputs:

- `total_score`
- `bull_prob` / `bear_prob`
- `reason_codes[]`
- `data_quality_flags[]`

## Scenario contract

Always return:

1. Primary scenario
2. Secondary scenario
3. No-trade scenario

Each scenario includes trigger, invalidation, targets, risk notes and reason codes.

## Paper simulation and gates

- Deterministic simulator stores outcomes (`pnl_pct`, `mfe_pct`, `mae_pct`) by horizon.
- Gate status computes sample size, winrate, profit factor, and max drawdown.
- Live execution stays disabled even when gate metrics pass.

- Gate thresholds are configurable via environment variables.

- Provider fallback is explicit and marks data degradation.


- Execution precheck blocks trades when: spread/slippage too high, volatility+thin liquidity, elevated event risk, data degraded, or execution disabled.
