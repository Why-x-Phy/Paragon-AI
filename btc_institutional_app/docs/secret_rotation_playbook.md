# Secret Management & Key Rotation Playbook

This playbook defines a minimum process for handling credentials in production.

## Scope

- Pionex API key/secret
- Coinglass API key
- Event calendar provider URL/token
- DB credentials and session secrets

## Baseline Controls

1. Prefer secret-file indirection (`*_FILE`) over inline env vars.
2. Never commit real secrets into git (`.env` stays local only).
3. Rotate credentials on a fixed schedule (at least every 90 days) and immediately after incident suspicion.
4. Use least privilege API keys (read-only where possible until execution rollout).

## Rotation Steps (Zero-Downtime Friendly)

1. **Create new secret** in your secret store/provider.
2. **Write new secret file** on host (e.g. `/run/secrets/pionex_api_key_next`).
3. **Update deployment env** to point `*_FILE` to the new path.
4. **Deploy/restart api service**.
5. **Verify health and key usage**:
   - `/api/v1/health`
   - `/api/v1/execution/reconcile`
6. **Revoke old key** in provider dashboard.
7. **Audit log entry**: who rotated, when, why, ticket/incident reference.

## Emergency Rotation

If compromise is suspected:

1. Disable execution: `EXECUTION_ENABLED=false`.
2. Revoke all active exchange/provider keys.
3. Issue fresh keys and redeploy using `*_FILE` paths.
4. Validate with health + reconcile endpoints.
5. Run post-incident review and update controls.

## Operational Checklist

- [ ] `.env` not present in git history.
- [ ] Production uses `*_FILE` for sensitive values.
- [ ] Last rotation timestamp recorded.
- [ ] Old key revoked and verified.
- [ ] Health/reconcile checks passed after deploy.
