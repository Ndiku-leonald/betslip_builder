# SlipIQ architecture

## Data flow

Provider adapters call API-Sports with server-side credentials. Responses are validated into provider-neutral models, mapped to canonical internal IDs, and upserted into SQLAlchemy entities. FastAPI returns normalized records to the Next.js viewer. Provider timestamps, ingestion timestamps, freshness, usage, and health are retained along the way.

## Canonical IDs

Internal UUID-like string identifiers are the primary application identifiers. `provider_entity_mappings` maps provider/entity identifiers to internal identifiers for fixtures, teams, competitions, players, and venues. Prediction, market, and slip layers will use internal IDs and remain provider-independent.

## Caching and quota

`CacheBackend` uses Redis when configured and an in-memory TTL cache otherwise. TTLs vary by resource and quota mode. `QuotaManager` records requests, cache hits, latency, status, remaining quota, and errors. It provides the seam for plan-aware daily limits and future distributed coordination.

## Background ingestion

APScheduler is an optional process-local scheduler. Free mode does not start aggressive polling. Explicit ingestion is available through the service/CLI, and scheduled jobs can be enabled with `ENABLE_SCHEDULED_INGESTION=true`. A future distributed queue can replace the scheduler without changing provider or persistence contracts.

## Future layers

The schema already reserves markets, odds, predictions, model versions, slips, and legs. These are intentionally inactive in Phase 1. Future model, market-selection, live-model, and optimizer services should consume normalized snapshots, freshness, and data-quality signals rather than provider payloads.

