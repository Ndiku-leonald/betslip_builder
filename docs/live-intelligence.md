# Stage Four — live / in-play intelligence

Stage Four extends the canonical Stage One–Three fixture and market layers. It does not replace a pre-match prediction. A live posterior starts with the latest `pre_match` prediction, incorporates the current score, clock/period, and legitimately available live evidence, and records the probability delta.

## Pipeline

`live fixtures → canonical fixture matching → immutable live state → freshness/data quality → pre-match prior → sport posterior → live odds validation → Stage Three value math → live ranking → API/UI`

`live_match_snapshots` and `live_prediction_snapshots` are append-only. A later observation corrects an earlier observation; current fixture fields remain a convenient index, not the audit history. `odds_snapshots` remains the Stage Three price source and `live_market_snapshots` records the decision context used for each live evaluation.

## Models and limits

Football uses a time-adjusted Poisson score distribution. The current score is hard state; expected goals, shots on target, xG, and red-card information adjust the remaining-goal intensities with explicit prior shrinkage. Basketball estimates remaining possessions and scoring from the pre-match expected score plus observed scoring rate, then uses normal uncertainty for margin and totals. These are defensible baselines, not claims of production calibration.

Dynamic live lines are marked `PARTIALLY_CALIBRATED` only when a calibrated pre-match prior exists; otherwise they are `UNCALIBRATED` or `INSUFFICIENT_EVIDENCE`. Synthetic tests do not establish real-world accuracy.

## Freshness and gates

The backend keeps source/provider time separate from local ingestion time. Defaults are configurable through `LIVE_DATA_STALE_SECONDS`, `LIVE_STATS_STALE_SECONDS`, and `LIVE_ODDS_STALE_SECONDS`. A stale state returns `Live data too stale for a reliable market evaluation.` A missing, stale, suspended, closed, or unavailable open price returns `Live market prices unavailable — no betting-market recommendation generated.` The last known state may still be displayed as stale.

Data quality is distinct from model confidence and can be `HIGH`, `MEDIUM`, `LOW`, or `UNUSABLE`. Single-source data is unverified, not 100% source agreement. Incomplete market groups are never no-vig normalized.

## API and UI

- `GET /api/live?sport=football|basketball` — live board cards.
- `GET /api/live/{fixture_id}` — current fixture and live prediction.
- `GET /api/live/{fixture_id}/prediction` — explicit pre-match/live comparison.
- `GET /api/live/{fixture_id}/markets` — live odds/value gate and ranked opportunities.
- `GET /api/live/{fixture_id}/history` — chronological immutable prediction snapshots.
- `POST /api/live/{fixture_id}/refresh` — quota-accounted, fixture-scoped provider refresh.

The `/live` board shows score, period/clock, state age, quality, pre-match probability, live probability, percentage-point delta, confidence, and calibration status. Fixture detail adds model, market, warnings, and history views.

## Operations

The existing APScheduler and persistent provider quota store remain the control plane. Free quota mode does not poll live providers. A standard/realtime deployment should run one scheduler process and keep API workers configured with scheduled ingestion disabled; the scheduler jobs are process-local. Caches retain upstream timestamps and never turn a cache hit into proof of fresh data.

API-Sports football/basketball remain the primary adapters, and the existing LiveScore football adapter remains secondary validation. The system does not scrape sites, invent missing stats/prices, bypass anti-bot controls, or claim a BetPawa public API.

Run the credential-free demo with:

```powershell
python -c "from app.live.synthetic_pipeline import run_synthetic_live_pipeline; print(run_synthetic_live_pipeline())"
```

Provider smoke tests are `SKIPPED — credentials unavailable` when keys are absent. This is expected and is not converted into a fabricated pass.
