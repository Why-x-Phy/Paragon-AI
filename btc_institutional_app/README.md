# BTC Institutional Trading Analysis Web App (VPS-Ready)

Private VPS-ready architecture for a BTC institutional analysis platform with explainable, probabilistic outputs and strict Paper→Live gating.

## Included in this revision

- Docker Compose stack (`nginx`, `api`, `worker`, `postgres`), port 80 exposed only.
- Basic Auth protected gateway for MVP (`admin / 0000`).
- FastAPI backend with regime-first analysis pipeline and reason-code scoring.
- MTF candle context (1m/5m/15m/1h/4h/1d) folded into ingestion baseline.
- Pattern-quality checks (ascending/rising wedge + fakeout risk) integrated into structure scoring baseline.
- Microstructure context (session VP/VWAP proxy + absorption/sweep risk) integrated into ingestion baseline.
- Nginx-served web dashboard (live cases, scenarios, alerts, gate status).
- Dashboard replay slider + chart overlay baseline (score/bull/bear lines).
- Feature persistence + raw snapshot persistence + alert generation + deterministic paper simulation outcomes.
- Signed execution client + reconciliation loop baseline (safe-gated) for phased live-readiness checks.
- Case logging and replay endpoints (`/v1/cases`, `/v1/cases/{id}`).
- SQL schema and docs for reproducibility and auditability.

## API contract (Phase 1)

- `POST /api/v1/analysis/run`
  - Input: normalized feature payload (`AnalysisInput`)
  - Output: explainable `AnalysisResponse` with scenarios and probabilities
- `POST /api/v1/ingestion/snapshot?symbol=BTCUSDT&run_analysis=true`
  - Pulls real-time market snapshot plus macro/derivatives/event context providers (with fallback/degradation notes), stores raw snapshot, and optionally runs analysis
- `GET /api/v1/raw_snapshots`
  - Lists latest raw provider snapshots for ingestion auditability
- `GET /api/v1/cases`
  - Lists stored analysis cases
- `GET /api/v1/cases/{id}`
  - Replays a stored case
- `GET /api/v1/cases/{id}/features`
  - Returns persisted feature snapshot for reproducibility
- `GET /api/v1/alerts`
  - Lists generated alerts
- `POST /api/v1/alerts/{id}/ack`
  - Marks an alert as acknowledged
- `POST /api/v1/cases/{id}/simulate?horizon=1h&chosen_scenario=primary`
  - Stores deterministic paper outcome metrics (PnL, MFE, MAE)
- `POST /api/v1/cases/{id}/simulate_realistic`
  - Stores cost-aware paper simulation (spread/slippage/fees + partial-fill ratio)
- `GET /api/v1/gates/status`
  - Reports paper-to-live gate readiness metrics (execution still disabled)
- `POST /api/v1/execution/precheck`
  - Runs hard pre-trade checks (spread/slippage/volatility/event/data quality + execution enabled flag)
- `POST /api/v1/execution/order`
  - Gated order endpoint (stubbed/real client depending on settings; blocked when execution disabled)
- `GET /api/v1/execution/reconcile`
  - Reconciliation snapshot: open orders, fills, positions, and mismatch warnings
- `GET /api/v1/execution/verify`
  - Connectivity + reconciliation diagnostics for signed exchange client baseline
- `POST /api/v1/risk/kill_switch/check`
  - Evaluates kill-switch triggers and persists risk events on breach
- `GET /api/v1/risk/events`
  - Lists persisted risk events for audit
- `GET /api/v1/health`
- `GET /api/v1/health/deep`
  - Extended health with DB/system metrics
- `GET /api/v1/metrics`
  - Lightweight operational counters
- `GET /api/v1/timeline/events`
  - Event severity timeline derived from raw snapshots

## Provider configuration notes

- `COINGLASS_API_KEY` enables real derivatives fan-in mapping (funding + open-interest change + liquidation totals).
- `EVENT_CALENDAR_URL` enables event-risk ingestion from one or more comma-separated JSON calendar feeds.
- `EVENT_CALENDAR_CURRENCY` filters events by target currency (default `USD`).
- `EVENT_CALENDAR_KEYWORDS` filters event names for priority macro events (default includes CPI/FOMC/NFP).
  - Accepted shapes: `{ "events": [...] }`, `{ "data": [...] }`, `{ "calendar": [...] }`, or a top-level array.
  - Supported event fields: timestamp/date/time/datetime + severity/impact/importance/priority.
- If these are not configured/reachable, ingestion is marked degraded with explicit event-calendar notes.
- `API_WRITE_TOKEN` (or `API_WRITE_TOKEN_FILE`) optionally protects mutating API routes (`POST` actions) via `X-Write-Token` header.

## Quick start

```bash
cd btc_institutional_app
cp config.example.env .env
# update credentials/secrets in .env
docker compose up --build -d
```

Open:
- `http://<VPS-IP>/` (Dashboard, Basic Auth)
- `http://<VPS-IP>/api/v1/health`


## TLS + Auth hardening baseline

- Default profile keeps HTTP + Basic Auth for quick start.
- TLS profile is available via compose override:

```bash
docker compose -f docker-compose.yml -f docker-compose.tls.yml up -d
```

Requirements:
- Place certs at `nginx/certs/fullchain.pem` and `nginx/certs/privkey.pem` (or mount equivalent).
- Nginx baseline includes security headers, API rate-limit (`limit_req`) and method restrictions on `/api/`.

## Notes

- This is Phase-1 analysis/paper foundation; no live execution.
- Keep secrets server-side only.
- For production, replace MVP credentials and add TLS.
- Use `*_FILE` secret indirection and follow `docs/secret_rotation_playbook.md`.
