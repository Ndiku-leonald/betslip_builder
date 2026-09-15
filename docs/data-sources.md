# Data sources

## API-Football

The adapter uses the official API-Sports host `v3.football.api-sports.io`. Phase 1 calls countries, leagues, teams, date fixtures, live fixtures, and fixture details; detail responses can include events, statistics, lineups, and players. Provider coverage varies by competition and plan.

API-Football fixture details can include events, statistics, lineups, and players when the competition and subscription cover them.

## API-Basketball

The adapter uses the official API-Sports basketball host `v1.basketball.api-sports.io`. Phase 1 calls countries, leagues, teams, date games, live games, game details, and the documented `games/statistics/teams` endpoint. Player statistics are exposed separately through `games/statistics/players`. Basketball status, periods, and scores are normalized independently from football; football events and lineups are not fabricated for basketball.

## Future sources

- The Odds API: secondary odds source behind an `OddsProvider` interface.
- Open-Meteo: weather snapshots keyed to fixtures and venues.
- BetPawa: only an approved feed/API via `BookmakerProvider`; no scraping or anti-bot bypass.
- Sofascore, LiveScore, and Flashscore: optional secondary verification only through approved integrations.

No future source should become a hidden production dependency. Every record must retain its source and freshness.
