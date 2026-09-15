# SlipIQ architecture

## Data flow

Provider adapters call API-Sports with server-side credentials. Responses are validated into provider-neutral models, mapped to canonical internal IDs, and upserted into SQLAlchemy entities. FastAPI returns normalized records to the Next.js viewer. Fixture kickoff, observation time, optional provider update time, freshness, usage, and health are retained separately along the way.

## Canonical IDs

Internal UUID-like string identifiers are the primary application identifiers. `provider_entity_mappings` maps provider/entity identifiers to internal identifiers for fixtures, teams, competitions, players, and venues. Prediction, market, and slip layers will use internal IDs and remain provider-independent.

## Caching and quota

`CacheBackend` uses Redis with JSON serialization when `REDIS_URL` is configured and reachable, and degrades to an in-memory TTL cache if Redis is unavailable. TTLs vary by resource and quota mode. `QuotaManager` enforces per-provider UTC-day limits; outbound retries consume quota, while cache hits do not. Provider usage persists each outbound attempt, including cache-hit status, latency, status, remaining quota, and errors.

## Background ingestion

APScheduler is an optional process-local scheduler. Free mode does not start aggressive polling. Explicit ingestion is available through the service/CLI, and scheduled jobs can be enabled with `ENABLE_SCHEDULED_INGESTION=true`. Do not enable it in every OS process of a multi-worker production deployment: run one dedicated scheduler process until a distributed queue replaces it.

## Future layers

The schema already reserves markets, odds, predictions, model versions, slips, and legs. These are intentionally inactive in Phase 1. Future model, market-selection, live-model, and optimizer services should consume normalized snapshots, freshness, and data-quality signals rather than provider payloads.
