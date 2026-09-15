# SlipIQ Stage Two modeling

Stage Two is a statistical research and pre-match probability layer. It does not create odds, value bets, optimized slips, or in-play recommendations.

## Data and leakage controls

Historical provider responses are normalized into `team_match_statistics`. Feature rows are generated in kickoff order. A fixture is appended to a team history, and its Elo rating is updated, only after that fixture's features are calculated. A target row therefore cannot use its own final result or any later fixture. Feature snapshots retain a UTC data cutoff and feature version.

Football features include short/medium recent form, goals, home/away splits, Elo, rest and congestion. The baseline score model uses Poisson expected goals and can use a configurable Dixon-Coles low-score correction (`MODEL_FOOTBALL_SCORE=dixon_coles`). The score matrix is converted to 1X2, double chance, BTTS, totals, team totals and supported handicap probabilities.

Basketball has a separate feature path, Elo, recent points/margins, rest and back-to-back indicators. Where box scores contain enough fields, SlipIQ derives estimated possessions and estimated offensive rating; these are explicitly estimates, not official league metrics. Expected scores use a normal margin/total approximation with variance estimated from training rows and a conservative fallback.

## Training and evaluation

`python -m app.training.train --sport football` and the basketball equivalent create a `candidate` model version. Models are never auto-promoted. Dataset splits are chronological. Walk-forward evaluation fits a model on the past, fits sigmoid calibration on a validation window only, and evaluates on a later test window. Reports include Brier score, log loss, expected calibration error and score error where applicable. Synthetic tests are not production performance claims.

Model versions persist algorithm, parameters, feature version, date ranges, sample count and metrics. Prediction records persist generated time, data cutoff, model version, feature version, feature-derived quality, confidence score and a compact payload.

## Responsible-use limits

Insufficient team history makes a prediction unavailable. Confidence is a data/model quality score, not another probability. No lineup, injury, bookmaker, closing-price or live model is claimed. Real historical training is required before presenting production model metrics.
