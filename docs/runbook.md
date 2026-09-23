# SlipIQ incident runbook

- API down: check container/process logs by request ID, `/livez`, and recent release; rollback the application image if needed.
- Readiness failure: inspect PostgreSQL connectivity/migration status and Redis ping. Do not hide a required Redis outage with memory fallback.
- Database failure: stop writes, preserve logs, check managed provider status, and restore only from an approved backup plan.
- Redis failure: verify URL/network/auth. Rate limiting, locks, and required cache semantics must remain degraded/failed explicitly.
- Provider outage or quota exhaustion: allow circuit recovery, inspect sanitized provider health/quota state, and do not increase polling/retry limits blindly.
- Stale live data: stop live recommendations until Stage Four freshness gates recover; never rewrite observation timestamps.
- Migration failure: stop rollout, inspect the migration transaction, restore application version, and forward-fix schema rather than blindly downgrading data-bearing production migrations.
- Worker stopped: check `APP_PROCESS_ROLE=worker`, scheduler logs, and duplicate-worker count; run one worker only.
- Frontend unavailable: verify Next.js process and API base URL; check security headers and browser-safe configuration.
- Excessive 429s: identify route/client patterns without retaining unnecessary personal data, then review limits; do not disable protection globally.
- Suspected credential exposure: revoke/rotate immediately, remove only from future history (not by rewriting Git), inspect logs/artifacts, and record the incident.
