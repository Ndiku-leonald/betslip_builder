# SlipIQ Stage Two modeling

Stage Two is a statistical research and pre-match probability layer. It does not create odds, value bets, optimized slips, or in-play recommendations.

## Data and leakage controls

Historical provider responses are normalized into `team_match_statistics`. Feature rows are generated in kickoff order. A fixture is appended to a team history, and its Elo rating is updated, only after that fixture's features are calculated. A target row therefore cannot use its own final result or any later fixture. Feature snapshots retain a UTC data cutoff and feature version.

Football features include short/medium recent form, goals, home/away splits, Elo, rest and congestion. The baseline score model uses Poisson expected goals and can use a configurable Dixon-Coles low-score correction (`MODEL_FOOTBALL_SCORE=dixon_coles`). The score matrix is converted to 1X2, double chance, BTTS, totals, team totals and supported handicap probabilities.

Basketball has a separate feature path, Elo, recent points/margins, rest and back-to-back indicators. Estimated possessions use `FGA + 0.44 * FTA - offensive_rebounds + turnovers` per team. When both team rows are present, `estimated_game_pace_avg_N` is their average; a team estimate is retained when only one row is available and its quality is reduced. It is never doubled. These are explicitly estimates, not official league metrics. Expected scores use a normal margin/total approximation with separate home-score and away-score residual standard deviations estimated from training rows and conservative fallbacks.

## Training and evaluation

`python -m app.training.train --sport football` and the basketball equivalent create a `candidate` model version. Models are never auto-promoted. Dataset splits are chronological. Walk-forward evaluation fits a model on the past, fits sigmoid calibration on a validation window only, and evaluates on a later test window. Production candidates persist calibrator parameters and status, so inference exposes raw and calibrated probabilities. Mutually exclusive and complementary markets are normalized or derived after calibration. Reports include proper multiclass 1X2 Brier/log loss, family-level binary Brier/log loss/ECE, and score error where applicable. Synthetic tests are not production performance claims.

Model versions persist algorithm, parameters, feature version, date ranges, sample count and metrics. Prediction records persist generated time, data cutoff, model version, feature version, feature-derived quality, confidence score and a compact payload.

## Responsible-use limits

Insufficient team history makes a prediction unavailable. Confidence is a data/model quality score, not another probability. No lineup, injury, bookmaker, closing-price or live model is claimed. Real historical training is required before presenting production model metrics.
