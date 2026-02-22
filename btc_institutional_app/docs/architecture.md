# Architecture Blueprint

## Deployment target

- Ubuntu VPS
- Docker Compose stack
- Exposed: port 80 only
- Access: `http://<VPS-IP>`
- Auth: Basic Auth (MVP)

## Core components

1. **Nginx Gateway**
   - Basic auth
   - Serves dashboard static frontend
   - Reverse proxy for API
   - Future TLS termination (optional)

2. **FastAPI Backend**
   - Context provider fan-in at ingestion (market + macro + derivatives + event + microstructure)
   - Microstructure fan-in (depth + short horizon klines) for VP/VWAP and orderflow proxies
   - Optional external connectors: Coinglass API key and JSON calendar feed URL
   - Real event calendar ingestion supports multi-source JSON feeds with fallback
   - Regime-first engine sequence implemented in code
   - Scenario generation (Primary / Secondary / No-trade)
   - Explainable reason codes and penalties
   - Case/feature/score persistence
   - Alerts endpoint + ack flow + feature replay endpoint
   - Paper simulation endpoint + gate status endpoint + execution precheck/order stubs (gated)

3. **Worker**
   - Generates normalized ingestion payloads on interval
   - Calls API to create analysis cases continuously
   - Placeholder for replacing synthetic feed with real providers

4. **Postgres**
   - Raw snapshots + cases/features/scenarios/scores/alerts/outcomes for reproducibility and audit

## Security baseline

- No API keys in frontend.
- DB not publicly exposed.
- `EXECUTION_ENABLED=false` default.
- Secret file indirection (`*_FILE`) supported for sensitive settings.
- Live trading hard-gated behind paper performance metrics.

## Current APIs

- `POST /v1/analysis/run`
- `POST /v1/ingestion/snapshot`
- `GET /v1/raw_snapshots`
- `GET /v1/cases`
- `GET /v1/cases/{id}`
- `GET /v1/cases/{id}/features`
- `GET /v1/alerts`
- `POST /v1/alerts/{id}/ack`
- `POST /v1/cases/{id}/simulate`
- `POST /v1/cases/{id}/simulate_realistic`
- `GET /v1/gates/status`
- `POST /v1/execution/precheck`
- `POST /v1/execution/order`
- `GET /v1/execution/reconcile`
- `GET /v1/execution/verify`
- `POST /v1/risk/kill_switch/check`
- `GET /v1/risk/events`
- `GET /v1/health`
- `GET /v1/health/deep`
- `GET /v1/metrics`
- `GET /v1/timeline/events`


## TLS profile

- Use `docker-compose.tls.yml` override to enable HTTPS (443) and HTTP->HTTPS redirect.
- TLS config lives in `nginx/tls.conf`; certificates are mounted from `nginx/certs/`.
- Gateway hardening includes security headers, API rate-limits, and method restrictions.


## Write-route identity hardening

- Mutating API routes support optional backend token gate via `API_WRITE_TOKEN`/`API_WRITE_TOKEN_FILE`.
- Clients must send `X-Write-Token` for write calls when token gating is enabled.
