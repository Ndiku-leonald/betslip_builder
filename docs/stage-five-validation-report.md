# Stage Five validation report

Validation was run on `develop` at the Stage Five implementation commit.

## Implementation

- Added `app.slips` candidate pool, centralized eligibility gates, profile presets, transparent correlation classifications, deterministic beam search, push-aware metrics, persistence, timestamp-safe optimizer evaluation and a credential-free synthetic pipeline.
- Extended the original Phase One slip tables with exact odds-snapshot references and immutable recommendation snapshots through migration `0009_stage_five_slip_optimizer`.
- Added `POST /api/slips/build`, slip retrieval/explanation/history, leg removal/recalculation, and the Next.js `/builder` page.
- Default build mode is a single provider/bookmaker group. No automatic bookmaker action exists.

## Validation matrix

| Check | Result |
| --- | --- |
| Backend total | 101 passed |
| Focused Stage Five | 8 passed |
| Frontend lint | PASS |
| Frontend typecheck | PASS |
| Frontend Vitest | 3 files / 3 tests passed |
| Frontend production build | PASS; `/builder` generated |
| Migration cycle | `upgrade head` PASS; `downgrade -1` PASS; `upgrade head` PASS |
| Stage Two synthetic | PASS; 28 historical rows, 17/5/6 split |
| Stage Three synthetic | PASS; canonical market/value checks |
| Stage Four football synthetic | PASS |
| Stage Four basketball synthetic | PASS |
| Stage Five synthetic | PASS |
| Optimizer backtest | PASS; 2-row software fixture, target rate 50%, observed all-leg hit rate 50% |
| `GET /health` | HTTP 200 |
| Provider smoke tests | SKIPPED — credentials unavailable |

## Stage Five scenarios

- A — Conservative, target 3.00: `TARGET_REACHED`, best 2.89, 2 legs, one synthetic bookmaker.
- B — Balanced, target 5.00: `TARGET_REACHED`, best 5.06, 3 legs, one synthetic bookmaker.
- C — Aggressive, target 10.00: `TARGET_REACHED`, best 10.62, 5 legs, one synthetic bookmaker.
- D — Conservative impossible target 50.00 with max three legs: `NO_SAFE_TARGET`; closest safe option was returned where available and hard gates were preserved.

Synthetic tests validate software behavior, not real-world betting accuracy or profitability. Odds and probabilities remain estimates, and selections can lose.
