# Odds and market contract

## Configure The Odds API

The repository already includes a The Odds API adapter for real bookmaker prices. Add the key to your local `.env` file; do not put it in source code or `.env.example`:

```dotenv
THE_ODDS_API_KEY=PASTE_YOUR_KEY_HERE
THE_ODDS_API_BASE_URL=https://api.the-odds-api.com/v4
ENABLE_ODDS_API=true
```

The key is from [the-odds-api.com](https://the-odds-api.com/). Leave `ENABLE_ODDS_API=false` when the key is absent. Use the manual real-data smoke with a documented sport key after configuration:

```powershell
Push-Location apps/api
python ..\..\scripts\real_data_smoke.py --odds-sport-key soccer_epl
Pop-Location
```

The smoke output is sanitized. It reports provider status and stored snapshot counts, never the key or request headers. A provider response is not treated as usable until its event is unambiguously matched to a canonical fixture.

## Market identity

An odds snapshot is identified by provider, bookmaker, internal fixture, market family, market type, period, participant, selection, line, and settlement semantics. `participant` is `home`, `away`, or `none`; it identifies the team side when a market needs one. `selection` is the outcome (`home`, `away`, `draw`, `over`, `under`, `yes`, `no`, or `win`). For example, a football home team total is `participant=home, selection=over, line=1.5`; an away handicap is `participant=away, selection=win, line=+0.5`.

`latest_market_snapshots()` returns one newest row per identity. `market_snapshot_history()` returns all append-only observations in chronological order and is used for movement charts only. Current value calculations never read the history query.

## Settlement and push handling

Model-market probabilities are stored as `win_probability`, `push_probability`, and `loss_probability`. No-push markets use `push_probability=0`. For refund-on-push markets:

```
EV = P(win) * (odds - 1) - P(loss)
fair_odds = 1 + P(loss) / P(win)
resolved_win_probability = P(win) / (P(win) + P(loss))
```

The resolved-outcome probability is the quantity used for price-edge comparison. It is distinct from unconditional win probability; a push returns stake and contributes zero to EV.

No-vig is calculated only for a complete, compatible current outcome set: football 1X2 (`home`, `draw`, `away`), basketball moneyline (`home`, `away`), BTTS (`yes`, `no`), and totals (`over`, `under`). The rows must share bookmaker, fixture, period, line, settlement semantics, and current snapshot identity. Incomplete groups expose `no_vig_status=incomplete_market` and keep no-vig probability and edge null.

Fixture-level value results keep explicit decisions: `SUPPORTED`, `UNSUPPORTED`, `INCOMPATIBLE_SETTLEMENT`, `INSUFFICIENT_MODEL`, `INSUFFICIENT_CALIBRATION`, `INCOMPLETE_MARKET`, and `STALE_PRICE`. The Value Finder filters blocked decisions; the fixture view keeps them visible with their reason.

Across bookmakers, compatible current selections expose best price, median price, median raw implied probability, and the contributing bookmakers. The grouping key includes provider, fixture, family, type, period, participant, selection, line, and settlement semantics; median pricing limits the influence of one outlier book.

## Provider timestamps

`observed_at` is when SlipIQ fetched a quote. `provider_updated_at` is the source-reported price update time. The Odds API uses `market.last_update`, falling back to `bookmaker.last_update`; API-Sports preserves an update timestamp when the response supplies one. Freshness prefers provider price age and falls back to fetch age, exposing both `price_age_seconds` and `fetch_age_seconds`.

## Normalization

The Odds API h2h and spread outcomes use actual team names. They are mapped to home or away only by exact normalized equality with the event's `home_team` and `away_team`; unmatched team outcomes are rejected as ambiguous. Draw, Over, and Under are normalized as selections. Team totals retain both participant and Over/Under selection. API-Sports totals and handicaps use structured line fields when present and extract a number only from an explicit market label when the structured value is absent.

## Calibration and reliability

Persisted Stage Two probabilities are marked `fitted` only when the exact market calibrator is fitted. Arbitrary lines evaluated directly from the statistical model are marked `raw_dynamic_line` and are not presented as calibrated. Conservative ranking requires fitted calibration; balanced ranking accepts fitted or family evidence; aggressive ranking may accept a raw dynamic line when its other gates pass.

`market_reliability` is calculated from Stage Two backtest sample count, calibrated ECE, Brier score, log loss, and coverage. No evidence produces unknown/low reliability. It is separate from `source_reliability`, which describes provider/source priority, freshness, coverage, and observed agreement.
