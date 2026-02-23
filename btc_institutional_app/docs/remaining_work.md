# Remaining Work Tracker

This file tracks major gaps to reach the full institutional target.


## Definition of Done (institutional target)
- [ ] End-to-end ingestion + analysis + persistence + replay works without degraded provider paths for normal operations.
- [ ] Paper-to-live gates show green for a sustained burn-in period and are documented with owner sign-off.
- [ ] Execution precheck/reconcile/verify and risk kill-switch are tested in staged incidents.
- [ ] Production observability includes external dashboards and actionable alerts tied to runbooks.
- [ ] Secret rotation process is exercised in production and evidence is captured in ops records.

## Data & Engines
- [x] Real Coinglass integration baseline shipped: funding + OI + liquidation endpoints with retry/ratelimit degradation.
- [x] Real economic calendar hardening shipped: multi-source coverage scoring, relevance filtering, and low-coverage degradation notes.
- [x] Replaced event policy stub with real calendar provider connector and degraded fallback signals.
- [x] Multi-timeframe candle feature builder extended with alignment ratio and trend-bias context (1m/5m/15m/1h/4h/1d).
- [x] Pattern validation depth upgraded with MTF alignment and VWAP-slope confirmation signals.
- [x] Volume profile / anchored VWAP depth expanded (value acceptance + VWAP slope context).
- [x] Orderflow/depth analytics upgraded with orderbook imbalance and depth-thinness signals.

## Paper & Execution
- [x] Realistic paper fill model (spread, slippage, fees, partial fills) baseline implemented.
- [x] Signed Pionex client baseline now includes verification endpoint for connectivity + reconciliation diagnostics.
- [x] Risk kill-switch policy checks with persisted breach events implemented.

## Security & Ops
- [x] TLS hardening complemented with backend write-token identity gate for mutating API routes.
- [x] Secret management + key rotation playbook documented; runtime `*_FILE` secret loading baseline shipped.
- [x] Structured request logs + metrics + deep health probes baseline implemented (external dashboards pending).

## Open Follow-ups (current)
- [ ] Provision external dashboards + alerting for the shipped metrics/health probes (Grafana/Datadog/etc.) and link runbooks.
- [ ] Run the production secret-rotation checklist end-to-end and record the first verified rotation timestamp in operations docs.
- [ ] Add a smoke check in CI that verifies `*_FILE` secret loading still works for deployment manifests.

## Frontend
- [x] Frontend advanced chart depth shipped with additional market-structure overlays and replay continuity controls.
- [x] Dedicated panels for derivatives, macro, event risk timeline (baseline static dashboard).
