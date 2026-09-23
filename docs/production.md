# SlipIQ production guide

## Architecture

Run the Next.js frontend, FastAPI API web process, one or more API worker replicas with exactly one scheduler worker role, PostgreSQL, and Redis. `APP_PROCESS_ROLE=web` never starts scheduled ingestion in production; `APP_PROCESS_ROLE=worker` is the only scheduled-job role. Use a single worker replica unless the scheduler lock/leader mechanism is extended and tested.

SQLite and the in-memory cache are for development/tests. Production fails closed unless `DATABASE_URL` is PostgreSQL and Redis is configured and reachable. Use the supplied Compose file for local production-like validation; its default password is intentionally local-only and must be replaced.

## Configuration and startup

Copy `.env.example` to an untracked environment file and supply secrets through the deployment platform. Set explicit `ALLOWED_ORIGINS`, `TRUSTED_HOSTS`, `ADMIN_TOKEN`, PostgreSQL `DATABASE_URL`, and `REDIS_URL`. The API validates production configuration before serving. Apply migrations separately with `alembic upgrade head`; the API does not create production tables at startup.

Processes:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
APP_PROCESS_ROLE=worker python -m app.worker
npm run start
```

The standalone container runs `node .next/standalone/server.js`; use that command (with `PORT=3000`) in a container rather than a development server.

## Migrations and backups

Before a production migration: take a managed PostgreSQL backup or `pg_dump --format=custom "$DATABASE_URL" > backup.dump`; run `alembic upgrade head`; verify `/ready`; then restart API/worker processes. Do not automatically downgrade production. Prefer application rollback and a forward schema fix; restore a backup only under an incident decision. Restore with `pg_restore --clean --if-exists --dbname="$DATABASE_URL" backup.dump` after validating the target database.

## Security and operations

The API emits request IDs, structured redacted logs, security headers, sanitized errors, Prometheus-compatible `/metrics`, `/health`, `/ready`, and `/livez`. `/ready` checks database and required Redis; optional provider failures do not make the service unready. Expensive refresh/admin endpoints require a bearer token when configured and are rate limited. Never put credentials in URLs, logs, frontend `NEXT_PUBLIC_*` variables, or documentation.

Provider calls have bounded timeout/retry behavior, Retry-After handling, quota accounting, jitter, and a temporary circuit-open state. Old observations remain historical and are not timestamped as fresh after refresh failure. BetPawa remains disabled unless an approved feed is configured; no restricted scraping is supported.

## Validation

Run backend tests, frontend lint/typecheck/tests/build, migration upgrade/downgrade/upgrade, dependency/static scans, both container builds, and `python scripts/deployment_check.py`. Run `python scripts/performance_smoke.py` only against local/synthetic services. Provider smoke tests are `SKIPPED — credentials unavailable` when keys are absent.
