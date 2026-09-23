from __future__ import annotations

import numpy as np
from scipy.stats import norm


def _result(win: float, push: float = 0.0, *, calibration_status: str = "raw_dynamic_line") -> dict:
    win = float(max(0, min(1, win))); push = float(max(0, min(1 - win, push))); loss = float(max(0, 1 - win - push))
    return {"status": "SUPPORTED", "probability": win, "win_probability": win, "push_probability": push, "loss_probability": loss, "calibration_status": calibration_status}


def assess_market(market, *, model_settlement: str = "full_game") -> dict:
    """Return an explicit modelability decision before calculating a price."""
    if market.status != "open": return {"status": "UNSUPPORTED", "reason": f"market is {market.status}"}
    if market.settlement_semantics == "regulation" and model_settlement != "regulation": return {"status": "INCOMPATIBLE_SETTLEMENT", "reason": "model and market settle on different periods"}
    if market.market_family not in {"1x2", "draw_no_bet", "double_chance", "moneyline", "btts", "totals", "game_total", "team_total", "handicap", "spread"}: return {"status": "UNSUPPORTED", "reason": "no Stage Three model mapping"}
    expected = {"1x2": {"home", "draw", "away"}, "draw_no_bet": {"home", "away"}, "double_chance": {"home_draw", "draw_away", "home_away"}, "moneyline": {"home", "away"}, "btts": {"yes", "no"}, "totals": {"over", "under"}, "game_total": {"over", "under"}, "team_total": {"over", "under"}, "handicap": {"win"}, "spread": {"win"}}.get(market.market_family, set())
    if market.selection not in expected: return {"status": "UNSUPPORTED", "reason": "selection is not valid for this market family"}
    if market.line is None and market.market_family in {"totals", "game_total", "team_total", "handicap", "spread"}: return {"status": "UNSUPPORTED", "reason": "a line is required"}
    if market.market_family in {"team_total", "handicap", "spread"} and market.participant not in {"home", "away"}: return {"status": "UNSUPPORTED", "reason": "participant is required"}
    return {"status": "SUPPORTED", "reason": None}


def _resolved(win: float, push: float) -> dict:
    return _result(win, push)


def model_probability(model, row, market) -> dict:
    decision = assess_market(market, model_settlement="regulation" if market.sport == "football" else "including_overtime")
    if decision["status"] != "SUPPORTED": return {**decision, "probability": None, "win_probability": None, "push_probability": None, "loss_probability": None, "calibration_status": "insufficient_model"}
    if market.sport == "football":
        matrix = model.predict_distribution(row)
        if market.market_family == "1x2":
            win = {"home": np.tril(matrix, -1).sum(), "draw": np.trace(matrix), "away": np.triu(matrix, 1).sum()}[market.selection]
            return _resolved(float(win), 0.0)
        if market.market_family == "btts":
            yes = float(sum(matrix[i, j] for i in range(1, matrix.shape[0]) for j in range(1, matrix.shape[1])))
            return _resolved(yes if market.selection == "yes" else 1 - yes, 0.0)
        if market.market_family in {"totals", "game_total"}:
            line = float(market.line); win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j > line) if market.selection == "over" else sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j < line); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j == line)
            return _resolved(float(win), float(push))
        if market.market_family == "team_total":
            line = float(market.line); index = 0 if market.participant == "home" else 1; win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) > line) if market.selection == "over" else sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) < line); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) == line)
            return _resolved(float(win), float(push))
        if market.market_family == "handicap":
            line = float(market.line); win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i + line > j if market.participant == "home" else j + line > i)); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i + line == j if market.participant == "home" else j + line == i))
            return _resolved(float(win), float(push))
    else:
        home, away = model._scores(row); margin, total = home - away, home + away
        if market.settlement_semantics == "regulation": return {"status": "INCOMPATIBLE_SETTLEMENT", "probability": None, "win_probability": None, "push_probability": None, "loss_probability": None, "calibration_status": "insufficient_model", "reason": "basketball model represents game outcome, not regulation-only outcome"}
        if market.market_family == "moneyline": return _resolved(float(norm.cdf(margin / model.margin_sd)) if market.selection == "home" else float(norm.cdf(-margin / model.margin_sd)), 0.0)
        if market.market_family in {"spread", "handicap"}:
            value = (margin + float(market.line)) if market.participant == "home" else (-margin + float(market.line)); return _resolved(float(norm.cdf(value / model.margin_sd)), 0.0)
        if market.market_family in {"game_total", "totals"}:
            value = (total - float(market.line)) / model.total_sd; return _resolved(float(norm.cdf(value)) if market.selection == "over" else float(norm.cdf(-value)), 0.0)
        if market.market_family == "team_total":
            score = home if market.participant == "home" else away; sd = model.home_score_sd if market.participant == "home" else model.away_score_sd; value = (score - float(market.line)) / sd; return _resolved(float(norm.cdf(value)) if market.selection == "over" else float(norm.cdf(-value)), 0.0)
    return {"status": "UNSUPPORTED", "probability": None, "win_probability": None, "push_probability": None, "loss_probability": None, "calibration_status": "insufficient_model", "reason": "market not mapped"}


def model_probability_scalar(model, row, market) -> float | None:
    return model_probability(model, row, market).get("probability")
