# SlipIQ Stage Five — Betslip Builder

Stage Five adds a bounded, analytical target-odds optimizer on top of the canonical Stage Three market-value and Stage Four live-intelligence services. It does not place bets and does not describe any selection as guaranteed, certain, fixed, risk-free, or guaranteed profit.

## Candidate flow

`Fixture -> latest canonical OddsSnapshot -> linked feature snapshot -> champion-backed Stage Two prediction -> Stage Three value/freshness/compatibility -> Stage Four live gate (live only) -> centralized Stage Five gate -> bookmaker-grouped optimizer`

The builder uses the latest valid snapshot for each canonical fixture/market/line/settlement identity. Pre-match candidates use Stage Three valuation. Live candidates are produced by `LiveIntelligenceService.markets`, which preserves the live state, price freshness and recommendation gates. Finished fixtures, suspended/closed/unavailable markets, stale prices, invalid odds, missing model probabilities, unsupported settlement semantics, provider conflicts, unacceptable quality/confidence, and unaccepted calibration are excluded with diagnostic reasons.

When `real_only=true`, the optimizer also requires a non-synthetic canonical provider fixture, a persisted feature snapshot linked by feature version, a persisted prediction whose model version is currently `champion`, and a non-synthetic odds snapshot. Missing or broken lineage is a hard rejection and cannot be bypassed by a lower profile or a higher target tolerance.

## Profiles and search

Profile thresholds and weights live in `app/slips/config.py`. Conservative emphasizes probability, calibration, quality, reliability and fewer legs. Balanced trades those signals against target fit and value. Aggressive permits lower—but still bounded and modeled—probability and quality thresholds; it never permits broken, stale or unsupported markets.

The optimizer groups selections by `(provider, bookmaker)` so a user-facing slip is buildable at one source. It prunes to the top eight candidates per fixture and a maximum of 120 candidates per bookmaker group, then performs deterministic beam search with a maximum width of 160 and the configured leg limit. The objective combines:

- target fit using logarithmic odds distance and target tolerance;
- naive all-legs win probability;
- a conservative correlation-adjusted probability score;
- confidence, data quality, market/source reliability, value and leg-count quality;
- uncertainty and concentration penalties.

Same-fixture selections are rejected by default. The correlation engine labels pairs `LOW`, `MODERATE`, `HIGH`, `CONFLICTING`, or `UNKNOWN`; it does not invent a precise covariance without evidence. Joint win probability is the product of leg win probabilities for the approximately independent case. Push probability remains on each leg and in the fair-price calculation; integer lines are not treated as half-point lines.

If the requested target is not reachable within tolerance, the API returns `NO_SAFE_TARGET` and explains that constraints were not weakened. A closest feasible option may still be returned when available. Alternatives must differ by at least two fixture identities where enough candidates exist.

## Persistence and APIs

Migration `0009_stage_five_slip_optimizer` extends the original `slips` and `slip_legs` tables. Each slip stores profile, mode, target/achieved odds, optimization version, probability scores, correlation risk, configuration, warnings and diagnostics. Each leg stores the exact odds snapshot reference and an immutable JSON snapshot of fixture, market, bookmaker, model, quality, freshness and explanation fields.

- `POST /api/slips/build`
- `GET /api/slips/{slip_id}`
- `GET /api/slips/{slip_id}/explain`
- `GET /api/slips/history`
- `DELETE /api/slips/{slip_id}/legs/{leg_id}`

Requests are bounded to a target up to 1000, a maximum of 12 legs, and a date window up to 31 days. Removing a leg recalculates combined odds and probability from the stored prices without refetching providers.

## Frontend and evaluation

The `/builder` page exposes sport, target, profile, leg bounds, live inclusion and quality controls. It shows the selected bookmaker, exact odds, model probability, confidence, data quality, correlation risk, explanations and alternative options. It also shows explicit no-data and impossible-target states.

The timestamp-safe evaluation helper in `app/slips/backtest.py` measures target achievement, achieved odds, leg counts, predicted probability, all-leg hit rate, EV estimates, calibration buckets and correlation-risk distribution. Historical evaluation must supply only information available at `selection_at`; a small or synthetic sample is not evidence of real-world accuracy or profitability.

The credential-free synthetic pipeline covers conservative, balanced, aggressive, football-only, basketball-only, mixed-sport, target-fit and impossible-target behavior. Synthetic tests validate software behavior, not real-world betting accuracy or profitability.
