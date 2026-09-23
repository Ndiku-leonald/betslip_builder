from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm, poisson

from app.live.state import LiveMatchState


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return float(max(low, min(high, value)))


def _poisson_matrix(home: float, away: float, cap: int = 12) -> np.ndarray:
    values = np.arange(cap + 1)
    matrix = np.outer(poisson.pmf(values, max(.01, home)), poisson.pmf(values, max(.01, away)))
    return matrix / matrix.sum()


def _value(statistics: dict, side: str, *keys: str) -> float | None:
    row = statistics.get(side, {}) if isinstance(statistics, dict) else {}
    for key in keys:
        if row.get(key) is not None:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                return None
    return None


@dataclass(frozen=True)
class FootballLivePosterior:
    state: LiveMatchState
    home_remaining_mean: float
    away_remaining_mean: float
    distribution: np.ndarray
    pre_match_probability: dict
    live_probability: dict
    confidence_evidence: float
    method: str = "time_adjusted_poisson_bayesian_update_v1"

    @classmethod
    def from_prior(cls, state: LiveMatchState, prior: dict | None = None) -> "FootballLivePosterior":
        prior = prior or {}
        current_home = float(state.home_score or 0)
        current_away = float(state.away_score or 0)
        minute = max(0.0, min(90.0, float(state.minute or 0)))
        remaining_fraction = max(0.02, (90.0 - minute) / 90.0)
        prior_home = float(prior.get("expected_home_goals", 1.35))
        prior_away = float(prior.get("expected_away_goals", 1.05))
        # A conjugate-style shrinkage update: prior scoring rates retain weight
        # early, while xG and shot evidence get more weight as the match ages.
        xg_home = _value(state.statistics, "home", "expected_goals", "xg")
        xg_away = _value(state.statistics, "away", "expected_goals", "xg")
        shots_home = _value(state.statistics, "home", "shots_on_goal", "shots_on_target")
        shots_away = _value(state.statistics, "away", "shots_on_goal", "shots_on_target")
        observed_home = xg_home if xg_home is not None else (shots_home * 0.28 if shots_home is not None else None)
        observed_away = xg_away if xg_away is not None else (shots_away * 0.28 if shots_away is not None else None)
        evidence_fraction = max(0.0, min(1.0, minute / 90.0))
        evidence_strength = evidence_fraction * (0.75 if observed_home is not None or observed_away is not None else 0.2)
        def rate(prior_rate: float, observed: float | None) -> float:
            baseline = prior_rate * evidence_fraction
            if observed is None:
                return max(.01, baseline)
            observed_rate = observed / max(.15, evidence_fraction)
            return max(.01, (baseline * (1.0 - evidence_strength) + observed_rate * evidence_strength) * remaining_fraction)
        home_remaining = rate(prior_home, observed_home)
        away_remaining = rate(prior_away, observed_away)
        red_home = _value(state.statistics, "home", "red_cards") or sum(1 for e in state.events if str(e.get("team", {}).get("id")) and str(e.get("type", "")).lower() in {"red card", "red_card"} and str(e.get("side")) == "home")
        red_away = _value(state.statistics, "away", "red_cards") or 0
        if red_home and red_home > 0: away_remaining *= 1.0 + min(.35, .12 * red_home); home_remaining *= max(.65, 1.0 - .10 * red_home)
        if red_away and red_away > 0: home_remaining *= 1.0 + min(.35, .12 * red_away); away_remaining *= max(.65, 1.0 - .10 * red_away)
        matrix = _poisson_matrix(current_home + home_remaining, current_away + away_remaining)
        home_win = float(np.tril(matrix, -1).sum()); draw = float(np.trace(matrix)); away_win = float(np.triu(matrix, 1).sum())
        live = {"home_win": home_win, "draw": draw, "away_win": away_win}
        pre = {key: float(prior[key]) for key in ("home_win", "draw", "away_win") if isinstance(prior.get(key), (int, float))}
        if len(pre) != 3:
            pre_matrix = _poisson_matrix(prior_home, prior_away)
            pre = {"home_win": float(np.tril(pre_matrix, -1).sum()), "draw": float(np.trace(pre_matrix)), "away_win": float(np.triu(pre_matrix, 1).sum())}
        evidence = _clamp(evidence_fraction * (1.0 if state.statistics else .45) * (1.0 if state.provider_updated_at else .8))
        return cls(state, home_remaining, away_remaining, matrix, pre, live, evidence)

    def probabilities_for_market(self, market) -> dict:
        matrix = self.distribution
        family, selection, line, participant = market.market_family, market.selection, market.line, market.participant
        if family == "1x2": win = {"home": np.tril(matrix, -1).sum(), "draw": np.trace(matrix), "away": np.triu(matrix, 1).sum()}[selection]; push = 0.0
        elif family == "btts":
            yes = sum(matrix[i, j] for i in range(1, matrix.shape[0]) for j in range(1, matrix.shape[1])); win = yes if selection == "yes" else 1 - yes; push = 0.0
        elif family in {"totals", "game_total"}:
            line = float(line); win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j > line) if selection == "over" else sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j < line); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if i + j == line)
        elif family == "team_total":
            line = float(line); index = 0 if participant == "home" else 1; win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) > line) if selection == "over" else sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) < line); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i if index == 0 else j) == line)
        elif family in {"handicap", "spread"}:
            line = float(line); win = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i + line > j if participant == "home" else j + line > i)); push = sum(matrix[i, j] for i in range(matrix.shape[0]) for j in range(matrix.shape[1]) if (i + line == j if participant == "home" else j + line == i))
        else: return {"status": "UNSUPPORTED", "reason": "live football market is not supported"}
        win, push = _clamp(float(win)), _clamp(float(push), 0.0, 1.0 - _clamp(float(win)))
        return {"status": "SUPPORTED", "win_probability": win, "push_probability": push, "loss_probability": max(0.0, 1.0 - win - push), "calibration_status": "PARTIALLY_CALIBRATED" if self.pre_match_probability else "UNCALIBRATED"}


def _elapsed_seconds(state: LiveMatchState) -> float:
    period_text = str(state.period or "").upper().replace("PERIOD", "").replace("Q", "").strip()
    try: period = int(float(period_text))
    except ValueError: period = 1
    clock = str(state.clock or "").strip()
    try:
        minutes, seconds = (int(part) for part in clock.split(":", 1))
        remaining = minutes * 60 + seconds
    except (ValueError, TypeError):
        remaining = 0
    return max(0.0, min(48 * 60, (period - 1) * 12 * 60 + (12 * 60 - remaining)))


@dataclass(frozen=True)
class BasketballLivePosterior:
    state: LiveMatchState
    expected_home_score: float
    expected_away_score: float
    margin_sd: float
    total_sd: float
    pre_match_probability: dict
    live_probability: dict
    confidence_evidence: float
    method: str = "remaining_possessions_normal_update_v1"

    @classmethod
    def from_prior(cls, state: LiveMatchState, prior: dict | None = None) -> "BasketballLivePosterior":
        prior = prior or {}
        current_home, current_away = float(state.home_score or 0), float(state.away_score or 0)
        elapsed = _elapsed_seconds(state); remaining = max(60.0, 48 * 60 - elapsed); fraction = remaining / (48 * 60)
        prior_home = float(prior.get("expected_home_score", 105.0)); prior_away = float(prior.get("expected_away_score", 102.0))
        prior_total = prior_home + prior_away
        current_total = current_home + current_away
        observed_rate = current_total / max(60.0, elapsed) * 60.0
        prior_rate = prior_total / (48 * 60) * 60.0
        evidence_weight = min(.8, max(.15, elapsed / (48 * 60))) if elapsed else .15
        remaining_rate = prior_rate * (1 - evidence_weight) + observed_rate * evidence_weight if elapsed else prior_rate
        expected_total = current_total + remaining_rate * (remaining / 60.0)
        prior_margin = prior_home - prior_away
        current_margin = current_home - current_away
        expected_margin = current_margin + prior_margin * fraction
        expected_home = (expected_total + expected_margin) / 2
        expected_away = (expected_total - expected_margin) / 2
        margin_sd = max(4.0, float(prior.get("margin_sd", 12.0)) * math.sqrt(max(.08, fraction)))
        total_sd = max(6.0, float(prior.get("total_sd", 18.0)) * math.sqrt(max(.08, fraction)))
        live = {"home_moneyline": float(norm.cdf(expected_margin / margin_sd)), "away_moneyline": float(norm.cdf(-expected_margin / margin_sd))}
        pre = {key: float(prior[key]) for key in ("home_moneyline", "away_moneyline") if isinstance(prior.get(key), (int, float))}
        if len(pre) != 2:
            pre = {"home_moneyline": float(norm.cdf(prior_margin / max(4.0, float(prior.get("margin_sd", 12.0))))), "away_moneyline": float(norm.cdf(-prior_margin / max(4.0, float(prior.get("margin_sd", 12.0)))))}
        return cls(state, expected_home, expected_away, margin_sd, total_sd, pre, live, _clamp(elapsed / (48 * 60)))

    def probabilities_for_market(self, market) -> dict:
        family, line, selection = market.market_family, float(market.line) if market.line is not None else None, market.selection
        margin = self.expected_home_score - self.expected_away_score; total = self.expected_home_score + self.expected_away_score
        if family == "moneyline": win = norm.cdf(margin / self.margin_sd) if selection == "home" else norm.cdf(-margin / self.margin_sd); push = 0.0
        elif family in {"spread", "handicap"}:
            value = margin + line if market.participant == "home" else -margin + line; win = norm.cdf(value / self.margin_sd); push = (norm.cdf((value + .5) / self.margin_sd) - norm.cdf((value - .5) / self.margin_sd)) if line is not None and line.is_integer() else 0.0
        elif family in {"game_total", "totals"}:
            value = (total - line) / self.total_sd; win = norm.cdf(value) if selection == "over" else norm.cdf(-value); push = (norm.cdf((line + .5 - total) / self.total_sd) - norm.cdf((line - .5 - total) / self.total_sd)) if line is not None and line.is_integer() else 0.0
        elif family == "team_total":
            score = self.expected_home_score if market.participant == "home" else self.expected_away_score; sd = self.total_sd / math.sqrt(2); value = (score - line) / sd; win = norm.cdf(value) if selection == "over" else norm.cdf(-value); push = 0.0
        else: return {"status": "UNSUPPORTED", "reason": "live basketball market is not supported"}
        win, push = _clamp(float(win)), _clamp(float(push), 0.0, 1.0 - _clamp(float(win)))
        return {"status": "SUPPORTED", "win_probability": win, "push_probability": push, "loss_probability": max(0.0, 1.0 - win - push), "calibration_status": "PARTIALLY_CALIBRATED" if self.pre_match_probability else "UNCALIBRATED"}
