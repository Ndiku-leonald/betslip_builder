# Historical data workflow

Backfills use the existing API-Sports provider, cache and quota accounting. They are resumable and idempotent: completed fixtures are upserted by provider identity, team-match statistics by fixture/team, and a checkpoint is written under `artifacts/checkpoints/` (generated files are ignored by Git).

Examples from `apps/api`:

```text
python -m app.historical.ingest_football --league 39 --season 2024 --start-date 2024-01-01 --end-date 2024-01-31 --max-requests 20
python -m app.historical.ingest_basketball --league 12 --season 2025 --start-date 2025-01-01 --end-date 2025-01-31 --no-stats
python -m app.historical.audit --sport football
python -m app.training.build_dataset --sport football --output artifacts/datasets/football.csv

# Explicit, one-request-per-league-season historical backfill (fixtures only)
python scripts/backfill_real_football.py --league 39 --league 140 --season 2024 --max-requests 2
```

Use `--dry-run`, narrow date ranges and `--max-requests` before a real backfill. The command summary separates logical operations, actual external requests, and cache hits. A retry is a real provider request and is charged to quota; cache hits are not. The provider request budget is applied before each retry, so `--max-requests` caps outbound attempts. API-Sports daily quota boundaries are UTC. Do not run a large backfill in CI or during local development without an explicit budget.

Football team statistics are normalized only when supplied by the provider. Basketball team statistics use the documented `games/statistics/teams` endpoint; player statistics are a separate capability using `games/statistics/players`. Unsupported or uncovered data is represented as unavailable, never fabricated.

The league-season command requires an explicit league list and a request cap. It intentionally omits match statistics; statistics must be requested separately with an additional budget because one stats request is charged per fixture.

CSV export is always available. Parquet export is supported when pandas and a parquet engine are installed. Audit output covers duplicate provider identities, invalid scores, competition counts, season/date coverage and snapshot counts. Generated datasets, checkpoints, model artifacts and runtime SQLite files are not source-controlled.
