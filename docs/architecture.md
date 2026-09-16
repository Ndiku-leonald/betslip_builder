# SlipIQ architecture

## Data flow

Provider adapters call upstream services with server-side credentials. Responses are validated into provider-neutral models, mapped to canonical internal IDs, and persisted into SQLAlchemy entities. FastAPI returns normalized records to the Next.js viewer. Fixture kickoff, observation time, optional provider update time, freshness, usage, and health are retained separately along the way. Stage Three odds are stored as immutable normalized snapshots rather than overwriting prior observations.

## Canonical IDs

Internal UUID-like string identifiers are the primary application identifiers. `provider_entity_mappings` maps provider/entity identifiers to internal identifiers for fixtures, teams, competitions, players, and venues. Prediction, market, and slip layers will use internal IDs and remain provider-independent.

## Caching and quota

`CacheBackend` uses Redis with JSON serialization when `REDIS_URL` is configured and reachable, and degrades to an in-memory TTL cache if Redis is unavailable. TTLs vary by resource and quota mode. `QuotaManager` enforces per-provider UTC-day limits using an injected `PersistentQuotaStore`: each real attempt reserves a `ProviderUsage` row before network I/O, so restarts cannot reset consumption. Outbound retries consume quota, while cache hits do not. A process-local lock prevents same-process races; future multi-process PostgreSQL deployments should replace the repository reservation with an atomic database lock/reservation. Provider usage persists each attempt, including cache-hit status, latency, status, remaining quota, and errors.

## Background ingestion

APScheduler is an optional process-local scheduler. Free mode does not start aggressive polling. Explicit ingestion is available through the service/CLI, and scheduled jobs can be enabled with `ENABLE_SCHEDULED_INGESTION=true`. Do not enable it in every OS process of a multi-worker production deployment: run one dedicated scheduler process until a distributed queue replaces it.

## Stage Three market layer

The schema reserves markets, odds, predictions, model versions, slips, and legs. Stage Three activates only the market-intelligence portion: normalized odds snapshots, provider conflicts, settlement-aware model compatibility, no-vig pricing, expected value, freshness gates, and profile-based ranking. Market and value services consume normalized snapshots, model outputs, freshness, and data-quality signals rather than provider payloads. Accumulator construction, live probability updates, and automated betting remain outside this stage.
