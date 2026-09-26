# Data sources

## API-Football

The adapter uses the official API-Sports host `v3.football.api-sports.io`. Phase 1 calls countries, leagues, teams, date fixtures, live fixtures, and fixture details; detail responses can include events, statistics, lineups, and players. Provider coverage varies by competition and plan.

API-Football fixture details can include events, statistics, lineups, and players when the competition and subscription cover them.

API-Football remains the primary football adapter. Standings, injuries, odds and live-detail coverage are checked against the provider response and subscription coverage; missing fields remain unavailable.

## football-data.org

The optional `football-data.org` v4 adapter is secondary validation only. The official API exposes competitions, matches/results, teams, standings, scorers and team match lists. It is not treated as a bookmaker-odds, lineup, injury or rich live-statistics source. Secondary observations are matched to the primary canonical fixture before they affect consensus and are not ingested as duplicate production fixtures.

## API-Basketball

The adapter uses the official API-Sports basketball host `v1.basketball.api-sports.io`. Phase 1 calls countries, leagues, teams, date games, live games, game details, and the documented `games/statistics/teams` endpoint. Player statistics are exposed separately through `games/statistics/players`. Basketball status, periods, and scores are normalized independently from football; football events and lineups are not fabricated for basketball.

## Stage Three sources

- The Odds API: optional bookmaker-price source behind an `OddsProvider` interface. Configure it in local `.env` with `THE_ODDS_API_KEY`, keep `THE_ODDS_API_BASE_URL=https://api.the-odds-api.com/v4`, and set `ENABLE_ODDS_API=true` only after the key is present. See [the-odds-api.com](https://the-odds-api.com/) for the provider account and documentation. The key is never committed, logged, or returned by the API.
- Open-Meteo: weather snapshots keyed to fixtures and venues.
- BetPawa: only an approved feed/API via `BookmakerProvider`; no scraping or anti-bot bypass. The import adapter is disabled by default.
- LiveScore Football: optional secondary football verification through the configured adapter. It never overwrites primary API-Sports observations by itself.
- EasySoccerData: isolated experimental adapter, disabled by default and never required by core ingestion.
- Sofascore and Flashscore: optional secondary verification only through approved integrations.

No source should become a hidden production dependency. Every record must retain its source and freshness. Provider conflicts remain observable instead of being silently averaged.

See [odds.md](odds.md) for provider timestamp precedence, exact team-name normalization, and the separation between source reliability and model-market reliability.
