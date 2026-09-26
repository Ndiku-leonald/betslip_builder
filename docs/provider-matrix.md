# SlipIQ provider matrix

This matrix records adapter behavior from the repository and the providers' published API documentation. Empty capability cells are intentionally `NO` or `UNKNOWN`; they are not inferred from similarly named products.

| Provider | Purpose | Fixtures / results | Standings | Team / player statistics | Lineups / injuries | Events | Live score / stats | Pre-match odds | Live odds | Bookmaker / market coverage | Rate / quota handling | SlipIQ status |
|---|---|---|---|---|---|---|---|---|---|---|---|
| API-Football | Primary football data | YES | Endpoint supported; plan coverage varies | Fixture statistics and player data where covered | Lineups and injuries where covered | YES | YES; statistics and odds are coverage/plan dependent | Endpoint supported; capture is required because history is limited | Endpoint supported; only current open prices qualify | Provider/bookmaker and market payloads normalized | Persistent request accounting, cache, retry and circuit breaker | Implemented primary adapter |
| API-Basketball | Primary basketball data | YES | API-Sports capability metadata | Team and player statistics | NO football lineups/injuries | NO football events | YES for basketball state/statistics | Fixture-scoped adapter if account exposes them | Fixture-scoped adapter if account exposes them | Normalized through Stage Three ontology | Persistent request accounting, cache, retry and circuit breaker | Implemented primary adapter |
| football-data.org | Secondary fixture/results/competition validation | YES | YES | NO rich team/player statistics in current adapter | NO | NO | NO rich live path in current adapter | NO | NO | No bookmaker/odds capability | Persistent SlipIQ quota accounting | Implemented secondary adapter |
| LiveScore Football adapter | Secondary live/fixture verification | YES | YES | Declared by adapter | UNKNOWN | YES | YES in configured adapter contract | NO demonstrated odds path | NO demonstrated odds path | UNKNOWN; do not assume bookmaker coverage | Cache only in current adapter | Implemented secondary, not authoritative |
| Fine Line Wire / live-in-play source | Intended live/in-play evaluation | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN | Official API identity/documentation is not present; no adapter added | UNKNOWN | Not integrated pending approved documentation |
| The Odds API | Odds context | Odds events, not canonical fixtures | NO | NO | NO | NO | Current/live event list only | YES for documented soccer markets where available | YES for documented live/upcoming markets where available | Bookmakers and markets depend on sport, region and plan | Upstream quota headers are surfaced; local accounting applies when a daily limit is configured | Implemented optional odds adapter |
| BetPawa | Approved bookmaker import target | NO public provider assumed | NO | NO | NO | NO | NO | NO | NO | Import only from an approved feed/API; no scraping or anti-bot bypass | N/A | Placeholder/import adapter only |
| EasySoccerData | Experimental isolated wrapper | NO core ingestion | UNKNOWN | Declared experimental statistics | UNKNOWN | Declared experimental events | Declared experimental live | NO | NO | UNKNOWN | Disabled by default; explicit client required | Experimental only |
| Additional provider slots 1–6 | Reserved football, basketball or all-sports sources | Not queried until an approved adapter is selected | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | Provider-specific; no capability is inferred from a base URL | Per-provider limits are added with the adapter | Configurable slots, adapter pending |

## Commissioning rules

- API-Football remains authoritative for canonical football fixtures unless a documented, recorded conflict is resolved through the consensus service.
- football-data.org observations are matched by normalized team names, competition and kickoff proximity; they are not written as duplicate canonical fixtures.
- Model probabilities and fair odds are never presented as bookmaker odds.
- If no configured provider returns real bookmaker prices, the report must say `REAL ODDS PROVIDER REQUIRED`.
- The Odds API requires `THE_ODDS_API_KEY` in local `.env` and `ENABLE_ODDS_API=true`; `THE_ODDS_API_BASE_URL` defaults to `https://api.the-odds-api.com/v4`.
- The 2026-09-26 credential probe returned 20 `soccer_epl` events. Odds are stored only after event-to-canonical-fixture matching; unmatched future events remain unpersisted.
- The final bounded activation returned 20 October EPL events with 488 upstream requests remaining and matched 0 events to the current canonical window; 0 odds snapshots were stored.
- Provider credentials are server-side environment variables only; `.env` is ignored by Git.
