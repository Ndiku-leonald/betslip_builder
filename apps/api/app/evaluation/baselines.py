from __future__ import annotations

from collections import Counter

from app.evaluation.metrics import brier_score, categorical_log_loss


def evaluate_baselines(rows, sport: str) -> dict:
    rows = [row for row in rows if row.actual]
    if not rows: return {}
    if sport == "football":
        counts = Counter("home" if row.actual["home_win"] else "draw" if row.actual["draw"] else "away" for row in rows); total = len(rows)
        probs = {key: counts[key] / total for key in ("home", "draw", "away")}; actual = ["home" if row.actual["home_win"] else "draw" if row.actual["draw"] else "away" for row in rows]
        rows_prob = [probs] * total
        elo_rows = []
        for row, actual_class in zip(rows, actual):
            home_score = 1 / (1 + 10 ** (-row.values.get("elo_diff", 60) / 400)); draw_score = .2; total_score = home_score + draw_score + (1 - home_score); elo_rows.append({"home": home_score / total_score, "draw": draw_score / total_score, "away": (1 - home_score) / total_score})
        poisson_rows = [{"home": probs["home"], "draw": probs["draw"], "away": probs["away"]}] * total
        return {"league_frequency_1x2": {"sample_count": total, "multiclass_brier": sum(sum((probs[k] - float(k == a)) ** 2 for k in probs) for a in actual) / total, "categorical_log_loss": categorical_log_loss(rows_prob, actual), "probabilities": probs}, "simple_elo_1x2": {"sample_count": total, "multiclass_brier": sum(sum((p[k] - float(k == a)) ** 2 for k in p) for p, a in zip(elo_rows, actual)) / total, "categorical_log_loss": categorical_log_loss(elo_rows, actual)}, "league_average_poisson": {"sample_count": total, "multiclass_brier": sum(sum((p[k] - float(k == a)) ** 2 for k in p) for p, a in zip(poisson_rows, actual)) / total, "categorical_log_loss": categorical_log_loss(poisson_rows, actual)}}
    home_rate = sum(row.actual["home_win"] for row in rows) / len(rows); outcomes = [row.actual["home_win"] for row in rows]
    elo_probs = [1 / (1 + 10 ** (-row.values.get("elo_diff", 65) / 400)) for row in rows]
    return {"home_win_frequency": {"sample_count": len(rows), "brier": brier_score([home_rate] * len(rows), outcomes), "mean_probability": home_rate}, "simple_elo_moneyline": {"sample_count": len(rows), "brier": brier_score(elo_probs, outcomes), "mean_probability": sum(elo_probs) / len(elo_probs)}, "league_average_score": {"sample_count": len(rows), "home_score": sum(row.actual["home_points"] for row in rows) / len(rows), "away_score": sum(row.actual["away_points"] for row in rows) / len(rows)}}
