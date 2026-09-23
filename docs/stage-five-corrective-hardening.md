# Stage Five corrective hardening

This corrective pass preserves the approved Stage One–Five architecture and hardens the existing target-odds optimizer.

## Selection and search

Pre-match candidate generation now selects the newest available `prediction_type=pre_match` prediction and ignores unavailable payloads. Snapshot identity includes fixture, provider, bookmaker, family/type, period, participant, selection, line, and settlement semantics; a current valid observation wins over a newer stale duplicate.

Candidates still pass the centralized Stage Three/Four status, freshness, compatibility, quality, confidence, reliability, calibration, fixture-status, and bookmaker gates. Build mode groups candidates by exactly one provider/bookmaker pair. The optimizer uses bounded beam search with per-fixture and per-group pruning, a maximum beam width, maximum legs, deterministic ordering, target-fit scoring, joint probability, value, reliability, quality, uncertainty, leg-count, and transparent correlation penalties.

Alternatives must differ by at least two fixture IDs from every previously selected alternative. Same-fixture selections remain one-leg-only by default.

## Probability and correlation

Independent-leg probability is exposed as a naive product. Push-capable legs retain win, push, and loss components; the UI/API expose all-win probability, no-loss-with-push probability, push-affected probability, and a warning that nominal odds can change under accumulator settlement.

Correlation uses qualitative `LOW`, `MODERATE`, `HIGH`, `CONFLICTING`, and `UNKNOWN` labels. Explicit football and basketball rules cover opposing results, totals, BTTS, team/game totals, moneyline/spread dependencies, and opposite handicaps. No numeric covariance is invented.

## Backtest contract

Historical rows are evaluated only when odds observation and prediction generation are at or before selection time, and pre-match selection time is before fixture start. Missing timestamps and leakage are counted separately. Outcome timestamps are used only after selection for scoring. Synthetic or small samples do not establish betting accuracy or profitability.

## UI and auditability

`/builder` exposes sport, date range, target, profile, live inclusion, confidence, data quality, probability, individual odds, tolerance, leg limits, and positive-value controls. Results show the bookmaker/provider, leg state, warnings, and push-aware metrics. Persisted legs contain immutable selection snapshots, exact odds, prediction/snapshot references, model metrics, and explanations. Deletion recalculates from stored snapshots without a provider refetch.

Synthetic scenarios A–D assert single-bookmaker construction, unique fixtures, current/open/supported selections, exact odds and joint products, non-increasing correlation adjustment, diverse alternatives, stale/suspended/unsupported rejection, and timestamp-safe backtesting.
