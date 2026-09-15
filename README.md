# SlipIQ

SlipIQ is a production-oriented sports data and statistical modeling foundation for football and basketball analytics. Stage Two adds historical, leakage-safe probability models and model review surfaces. It does not optimize slips, compare odds, place bets, or present fabricated selections.

## Stage One and Two status

- FastAPI backend with SQLAlchemy/Alembic and SQLite or PostgreSQL.
- API-Sports adapters for API-Football and API-Basketball.
- Canonical internal IDs, provider mappings, idempotent fixture upserts, freshness, cache, quota, and provider-health services.
- Next.js/React/Tailwind/TanStack Query frontend for dashboard, live fixtures, fixture details, and data sources.
- Unit/API tests, migration setup, CI, and architecture documentation.
- Historical backfill commands, normalized team-match statistics, chronological feature snapshots, football Poisson/Dixon-Coles and basketball expected-score baselines.
- Candidate model versioning, validation-only calibration, walk-forward evaluation, prediction API and a clearly labeled model-estimate tab on fixture pages.
- Evaluation splits are atomic by exact observation timestamp; same-kickoff fixtures remain in one partition. Candidate and fold-local baseline metrics use identical held-out fixture IDs, including a true league-average Poisson baseline.

## Architecture

```
apps/api       FastAPI, adapters, services, migrations, tests
apps/web       Next.js App Router frontend
docs           architecture and provider notes
```

External API keys stay server-side. Runtime data is real only when a provider is configured; otherwise the API returns a structured `provider_not_configured` response. Tests use mocked provider payloads and are never displayed as production data.

## Requirements

- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ for production (SQLite is automatic for local development)
- Redis is optional; SlipIQ uses Redis when `REDIS_URL` is configured and reachable, with an in-memory fallback when it is unavailable

## Setup

### Windows PowerShell

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
alembic -c apps/api/alembic.ini upgrade head
cd apps/web
npm install
```

### Linux / WSL

```bash
cp .env.example .env
python3 -m venv .venv && source .venv/bin/activate
pip install -r apps/api/requirements.txt
alembic -c apps/api/alembic.ini upgrade head
cd apps/web && npm install
```

Set `API_FOOTBALL_KEY` and/or `API_BASKETBALL_KEY` in `.env` using keys from the API-Sports dashboard. Never commit `.env`.

Optional quota overrides are `API_FOOTBALL_DAILY_LIMIT` and `API_BASKETBALL_DAILY_LIMIT`. Free mode defaults both providers to 100 outbound requests per UTC day. Real requests reserve persistent `ProviderUsage` rows before network I/O, so the allowance survives restarts; cache hits do not consume it and retries do. A process-local lock prevents same-process races. Multi-process deployments should use a shared database with an atomic reservation implementation before scaling API workers.

## Run

From the repository root, run the backend in one terminal:

```powershell
uvicorn app.main:app --app-dir apps/api --reload --port 8000
```

Run the frontend in another:

```powershell
cd apps/web
npm run dev
```

Ingest today's real data explicitly:

```powershell
Push-Location apps/api
python -m app.ingest --sport football --date 2026-09-14
python -m app.ingest --sport basketball --date 2026-09-14
Pop-Location
```

The backend exposes OpenAPI at http://localhost:8000/docs. The frontend is at http://localhost:3000.

Run the minimal real-provider smoke checks after configuring keys. The basketball check uses `games/statistics/teams` and reports `SKIPPED` when the returned competition has no team-stat coverage:

```powershell
Push-Location apps/api
python -m app.smoke_test
Pop-Location
```

Each operation reports `PASS`, `SKIPPED`, or `FAILED`; API keys are never printed. With no keys configured, all provider checks are `SKIPPED`.

## Quota and freshness

`QUOTA_MODE` accepts `free`, `standard`, or `realtime`. Free mode applies longer cache windows and avoids background polling. Fixture `kickoff_at` is separate from `observed_at` (the successful fetch time); `provider_updated_at` is only populated when the upstream supplies a trustworthy update time. Freshness and `data_age_seconds` use observation time, never kickoff time. The API exposes provider usage and health so stale or unavailable data is visible.

APScheduler is process-local. It is suitable for development and a single-worker deployment only. In production multi-worker FastAPI deployments, run the API with scheduled ingestion disabled in every worker and run one dedicated scheduler process (`ENABLE_SCHEDULED_INGESTION=true`) until a distributed job system is introduced.

## Real data limitations

Coverage varies by competition and subscription plan. Optional events, statistics, lineups, injuries, and odds may be unavailable. SlipIQ preserves that absence instead of inventing values. The frontend labels provider errors, stale data, and unavailable fields.

## Tests and checks

```powershell
python -m pytest apps/api/tests
cd apps/web
npm run lint
npm run typecheck
npm run test
npm run build
```

CI runs backend tests and frontend lint/typecheck/test/build without requiring paid provider credentials.

## Git workflow

Development happens on `develop`; `main` is not modified by Stage One or Stage Two. Commit meaningful milestones and push them to `origin/develop` for review.

## Stage Two research workflow

1. Configure one provider key and a deliberately small date range.
2. Run a quota-bounded historical backfill and inspect `python -m app.historical.audit --sport football`.
3. Build/export the dataset, train a `candidate`, review family-level walk-forward metrics and baseline comparisons, and activate a champion manually only after review (`python -m app.training.activate MODEL_VERSION_ID`).
4. Generate an upcoming-fixture prediction only when enough pre-match history exists.

See [docs/historical-data.md](docs/historical-data.md) and [docs/modeling.md](docs/modeling.md). Synthetic tests and the local pipeline are labeled test data; they are not evidence of real-world accuracy.

## Roadmap

Future reviewed phases may add market normalization, odds/value analysis, live probability updates, correlation-aware slip construction, and approved bookmaker feeds. They must preserve the canonical data layer and responsible-use boundaries.

## Responsible use

SlipIQ provides statistical decision support. Sports outcomes are uncertain. No output should be described as guaranteed, certain, or risk-free, and SlipIQ does not place bets automatically.
