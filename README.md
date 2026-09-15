# SlipIQ

SlipIQ is a production-oriented sports data foundation for football and basketball analytics. Phase 1 proves the path from real provider data to normalized storage, API endpoints, and a frontend viewer. It deliberately does not make predictions, place bets, or present fabricated selections.

## Phase 1 status

- FastAPI backend with SQLAlchemy/Alembic and SQLite or PostgreSQL.
- API-Sports adapters for API-Football and API-Basketball.
- Canonical internal IDs, provider mappings, idempotent fixture upserts, freshness, cache, quota, and provider-health services.
- Next.js/React/Tailwind/TanStack Query frontend for dashboard, live fixtures, fixture details, and data sources.
- Unit/API tests, migration setup, CI, and architecture documentation.

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
- Redis is optional; SlipIQ has an in-memory fallback

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

## Quota and freshness

`QUOTA_MODE` accepts `free`, `standard`, or `realtime`. Free mode applies longer cache windows and avoids background polling. Live records retain provider timestamps, ingestion timestamps, and a freshness classification. The API exposes provider usage and health so stale or unavailable data is visible.

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

Development happens on `develop`; `main` is not modified by Phase 1. Commit meaningful milestones and push them to `origin/develop` for review.

## Roadmap

Future reviewed phases may add market normalization, odds/value analysis, football and basketball models, live probability updates, correlation-aware slip construction, and approved bookmaker feeds. They must preserve the canonical data layer and responsible-use boundaries.

## Responsible use

SlipIQ provides statistical decision support. Sports outcomes are uncertain. No output should be described as guaranteed, certain, or risk-free, and SlipIQ does not place bets automatically.
