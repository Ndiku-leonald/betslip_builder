from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _line_key(prefix: str, line: float) -> str:
    return f"{prefix}_{str(float(line)).replace('.', '_')}"


def assess_market(market, *, model_settlement: str = "full_game") -> dict:
    """Return an explicit modelability decision before calculating a price."""
    if market.status != "open": return {"status": "UNSUPPORTED", "reason": f"market is {market.status}"}
    if market.settlement_semantics == "regulation" and model_settlement != "regulation":
        return {"status": "INCOMPATIBLE_SETTLEMENT", "reason": "model and market settle on different periods"}
    if market.market_family not in {"1x2", "moneyline", "btts", "totals", "game_total", "team_total", "handicap", "spread"}:
        return {"status": "UNSUPPORTED", "reason": "no Stage Three model mapping"}
    if market.line is None and market.market_family in {"totals", "game_total", "team_total", "handicap", "spread"}:
        return {"status": "UNSUPPORTED", "reason": "a line is required"}
    return {"status": "SUPPORTED", "reason": None}


def model_probability(model, row, market) -> dict:
    decision = assess_market(market, model_settlement="regulation" if market.sport == "football" else "including_overtime")
    if decision["status"] != "SUPPORTED": return {**decision, "probability": None}
    if market.sport == "football":
        matrix = model.predict_distribution(row); selection = market.selection
        if market.market_family == "1x2": key = {"home": "home_win", "draw": "draw", "away": "away_win"}[selection]; return {"status": "SUPPORTED", "probability": float(model._markets(matrix)[key]) if hasattr(model, "_markets") else float({"home": np.tril(matrix, -1).sum(), "draw": np.trace(matrix), "away": np.triu(matrix, 1).sum()}[selection])}
        if market.market_family == "btts":
            yes = float(sum(matrix[i, j] for i in range(1, matrix.shape[0]) for j in range(1, matrix.shape[1])))
            return {"status": "SUPPORTED", "probability": yes if selection == "yes" else 1 - yes}
        if market.market_family == "totals":
            line = float(market.line); over = float(sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j > line)); push = float(sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j == line)); return {"status": "SUPPORTED", "probability": over if selection == "over" else 1 - over - push, "push_probability": push}
        if market.market_family == "handicap":
            line = float(market.line); win = float(sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + line > j)); push = float(sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + line == j)); return {"status": "SUPPORTED", "probability": win, "push_probability": push}
    else:
        home, away = model._scores(row); margin, total = home - away, home + away
        if market.settlement_semantics == "regulation": return {"status": "INCOMPATIBLE_SETTLEMENT", "probability": None, "reason": "basketball model represents game outcome, not regulation-only outcome"}
        if market.market_family == "moneyline": return {"status": "SUPPORTED", "probability": float(norm.cdf(margin / model.margin_sd)) if market.selection == "home" else float(norm.cdf(-margin / model.margin_sd))}
        if market.market_family in {"spread", "handicap"}:
            value = margin + float(market.line) if market.selection == "home" else -margin + float(market.line); return {"status": "SUPPORTED", "probability": float(norm.cdf(value / model.margin_sd))}
        if market.market_family in {"game_total", "totals"}:
            value = (total - float(market.line)) / model.total_sd; return {"status": "SUPPORTED", "probability": float(norm.cdf(value)) if market.selection == "over" else float(norm.cdf(-value))}
        if market.market_family == "team_total":
            score = home if market.selection == "home" else away; sd = model.home_score_sd if market.selection == "home" else model.away_score_sd; value = (score - float(market.line)) / sd; return {"status": "SUPPORTED", "probability": float(norm.cdf(value)) if market.selection == "over" else float(norm.cdf(-value))}
    return {"status": "UNSUPPORTED", "probability": None, "reason": "market not mapped"}


def model_probability_scalar(model, row, market) -> float | None:
    return model_probability(model, row, market).get("probability")
