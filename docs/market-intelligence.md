# Stage Three market intelligence

Stage Three compares normalized bookmaker prices with the active model's supported probabilities. It is a research and decision-support surface; it does not create accumulators, place bets, or describe outcomes as certain.

## Data contract

Every odds record is normalized into an `OddsSnapshot` with the internal fixture ID, provider, bookmaker, market family, market type, period, participant, selection, line, decimal odds, status, settlement semantics, provider event ID, and observation timestamps. Snapshots are append-only so movement can be reconstructed and stale prices cannot silently replace history. See [odds.md](odds.md) for the canonical identity, timestamp, de-vig, and push-aware pricing contract.

Supported provider paths are:

- API-Sports fixture-scoped odds through the existing server-side API-Sports adapters.
- The Odds API behind `THE_ODDS_API_KEY` and the `OddsProvider` interface. Enable it with `ENABLE_ODDS_API=true` only after adding the key to local `.env`; the base URL is `https://api.the-odds-api.com/v4`.
- BetPawa import records only through an explicitly approved feed/API. Website scraping and anti-bot bypass are out of scope.
- LiveScore Football and EasySoccerData are secondary/experimental verification paths, isolated from the primary fixture path.

## Qualification

The value service calculates raw implied probability, no-vig probability when a complete market group is available, fair decimal odds, probability edge, and expected value. A result is not ranked unless:

- the price is open and within the configured freshness window;
- the market maps to a supported model probability;
- the market and model use compatible settlement semantics;
- model confidence and data-quality thresholds pass the selected risk profile; and
- the no-vig edge is positive above that profile's threshold.

Missing odds, unsupported markets, stale data, insufficient model support, incomplete markets, insufficient calibration, and provider failures remain explicit states on fixture-level Market intelligence. The Value Finder filters these states from ranked opportunities.

## Consensus and source agreement

The primary API-Sports fixture remains authoritative for canonical identity. A cached, conservatively matched LiveScore Football observation can verify a football fixture. Provider IDs are metadata and are never compared as team facts; consensus compares canonical team names, exact scores, normalized statuses, clock tolerance, and kickoff tolerance. Material conflicts are persisted once per unresolved fact and suppress opportunity ranking when the configured `MIN_PROVIDER_AGREEMENT` policy is not met. The secondary source is never presented as authoritative.

Provider observations are stored with source event ID, observation and update timestamps, kickoff, status, score, clock, period, canonical team mapping, and raw reference. Consensus reads recent stored observations before considering a narrowly scoped secondary fetch.

## API surfaces

- `GET /api/markets` — normalized odds snapshots.
- `GET /api/fixtures/{fixture_id}/markets` — latest fixture markets.
- `GET /api/fixtures/{fixture_id}/market-values` — supported model/price comparisons.
- `GET /api/opportunities` — ranked opportunities after profile filters.
- `GET /api/odds/movement` — append-only price movement history.
- `POST /api/fixtures/{fixture_id}/odds/refresh` and `POST /api/odds/refresh` — explicit provider refresh operations.
- `GET /api/data-sources` and `GET /api/conflicts` — source and disagreement observability.

The frontend exposes these through the Value Finder, fixture Market intelligence tab, and Data sources page.
