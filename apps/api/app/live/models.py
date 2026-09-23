from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm, poisson

from app.config import get_settings
from app.live.state import LiveMatchState


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return float(max(low, min(high, value)))


def _poisson_matrix(home: float, away: float, cap: int = 12) -> np.ndarray:
    values = np.arange(cap + 1)
    matrix = np.outer(poisson.pmf(values, max(.01, home)), poisson.pmf(values, max(.01, away)))
    return matrix / matrix.sum()


def _final_score_matrix(current_home: int, current_away: int, remaining_home: float, remaining_away: float, cap: int = 12) -> np.ndarray:
    """Translate a remaining-goals distribution into final-score space."""
    remaining = _poisson_matrix(remaining_home, remaining_away, cap)
    result = np.zeros((current_home + cap + 1, current_away + cap + 1), dtype=float)
    result[current_home:current_home + cap + 1, current_away:current_away + cap + 1] = remaining
    return result


def _discrete_normal(mean: float, standard_deviation: float, *, low: int, high: int) -> tuple[np.ndarray, np.ndarray]:
    values = np.arange(low, high + 1, dtype=int)
    probabilities = norm.cdf((values + .5 - mean) / standard_deviation) - norm.cdf((values - .5 - mean) / standard_deviation)
    probabilities = probabilities / probabilities.sum()
    return values, probabilities


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
    prior_was_observed: bool
    method: str = "time_adjusted_poisson_bayesian_update_v1"

    @classmethod
    def from_prior(cls, state: LiveMatchState, prior: dict | None = None) -> "FootballLivePosterior":
        prior = prior or {}
        current_home = float(state.home_score or 0)
        current_away = float(state.away_score or 0)
        minute = max(0.0, min(90.0, float(state.minute or 0)))
        remaining_fraction = max(0.0, (90.0 - minute) / 90.0)
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
        evidence_present = observed_home is not None or observed_away is not None
        evidence_strength = evidence_fraction * (.75 if evidence_present else 0.0)
        def full_match_intensity(prior_rate: float, observed: float | None) -> float:
            if observed is None or evidence_strength <= 0:
                return prior_rate
            observed_rate = observed / max(.15, evidence_fraction)
            return max(.01, prior_rate * (1.0 - evidence_strength) + observed_rate * evidence_strength)
        home_remaining = full_match_intensity(prior_home, observed_home) * remaining_fraction
        away_remaining = full_match_intensity(prior_away, observed_away) * remaining_fraction
        home_id = str(state.auxiliary.get("home_provider_id", ""))
        away_id = str(state.auxiliary.get("away_provider_id", ""))
        event_home_red = 0; event_away_red = 0
        for event in state.events:
            event_type = str(event.get("type", "")).lower()
            detail = str(event.get("detail", event.get("comments", ""))).lower()
            if "red" not in f"{event_type} {detail}":
                continue
            team_id = str((event.get("team") or {}).get("id", event.get("team_id", "")))
            if team_id and team_id == home_id: event_home_red += 1
            elif team_id and team_id == away_id: event_away_red += 1
        red_home = _value(state.statistics, "home", "red_cards")
        red_away = _value(state.statistics, "away", "red_cards")
        red_home = int(red_home) if red_home is not None else event_home_red
        red_away = int(red_away) if red_away is not None else event_away_red
        if red_home and red_home > 0: away_remaining *= 1.0 + min(.35, .12 * red_home); home_remaining *= max(.65, 1.0 - .10 * red_home)
        if red_away and red_away > 0: home_remaining *= 1.0 + min(.35, .12 * red_away); away_remaining *= max(.65, 1.0 - .10 * red_away)
        matrix = _final_score_matrix(int(current_home), int(current_away), home_remaining, away_remaining)
        home_win = float(np.tril(matrix, -1).sum()); draw = float(np.trace(matrix)); away_win = float(np.triu(matrix, 1).sum())
        live = {"home_win": home_win, "draw": draw, "away_win": away_win}
        pre = {key: float(prior[key]) for key in ("home_win", "draw", "away_win") if isinstance(prior.get(key), (int, float))}
        if len(pre) != 3:
            pre_matrix = _poisson_matrix(prior_home, prior_away)
            pre = {"home_win": float(np.tril(pre_matrix, -1).sum()), "draw": float(np.trace(pre_matrix)), "away_win": float(np.triu(pre_matrix, 1).sum())}
        evidence = _clamp(evidence_fraction * (1.0 if evidence_present else .45) * (1.0 if state.provider_updated_at else .8))
        return cls(state, home_remaining, away_remaining, matrix, pre, live, evidence, bool(prior))

    def probabilities_for_market(self, market) -> dict:
        matrix = self.distribution
        family, selection, line, participant = market.market_family, market.selection, market.line, market.participant
        if family == "1x2": win = {"home": np.tril(matrix, -1).sum(), "draw": np.trace(matrix), "away": np.triu(matrix, 1).sum()}[selection]; push = 0.0
        elif family == "draw_no_bet":
            win = np.tril(matrix, -1).sum() if selection == "home" else np.triu(matrix, 1).sum(); push = np.trace(matrix)
        elif family == "double_chance":
            outcomes = {"home_draw": np.tril(matrix, -1).sum() + np.trace(matrix), "draw_away": np.trace(matrix) + np.triu(matrix, 1).sum(), "home_away": np.tril(matrix, -1).sum() + np.triu(matrix, 1).sum()}; win = outcomes[selection]; push = 0.0
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
        return {"status": "SUPPORTED", "win_probability": win, "push_probability": push, "loss_probability": max(0.0, 1.0 - win - push), "calibration_status": "PARTIALLY_CALIBRATED" if self.prior_was_observed else "UNCALIBRATED"}


def _clock_context(state: LiveMatchState) -> tuple[float, float, float, bool]:
    settings = get_settings()
    period_minutes = int(state.auxiliary.get("period_minutes", settings.basketball_period_minutes))
    regulation_periods = int(state.auxiliary.get("regulation_periods", settings.basketball_regulation_periods))
    overtime_minutes = int(state.auxiliary.get("overtime_minutes", settings.basketball_overtime_minutes))
    rules_known = bool(state.auxiliary.get("rules_known", False))
    period_text = str(state.period or "").upper().replace("PERIOD", "").replace(" ", "")
    if period_text in {"HT", "HALFTIME"}:
        elapsed = regulation_periods * period_minutes * 60 / 2
        return elapsed, regulation_periods * period_minutes * 60, regulation_periods * period_minutes * 60 - elapsed, rules_known
    if period_text.startswith("OT"):
        suffix = period_text.removeprefix("OT") or "1"
        try: overtime_period = max(1, int(suffix))
        except ValueError: overtime_period = 1
        period_start = regulation_periods * period_minutes * 60 + (overtime_period - 1) * overtime_minutes * 60
        total = period_start + overtime_minutes * 60
    else:
        try: period = max(1, int(float(period_text.replace("Q", ""))))
        except ValueError: period = 1
        period_start = (period - 1) * period_minutes * 60
        total = regulation_periods * period_minutes * 60
    clock = str(state.clock or "").strip()
    try:
        minutes, seconds = (int(part) for part in clock.split(":", 1))
        remaining = minutes * 60 + seconds
    except (ValueError, TypeError):
        remaining = period_minutes * 60
    elapsed = period_start + max(0, min((overtime_minutes if period_text.startswith("OT") else period_minutes) * 60, (overtime_minutes if period_text.startswith("OT") else period_minutes) * 60 - remaining))
    return elapsed, total, max(0.0, total - elapsed), rules_known


def _elapsed_seconds(state: LiveMatchState) -> float:
    return _clock_context(state)[0]


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
    prior_was_observed: bool
    method: str = "remaining_possessions_normal_update_v1"

    @classmethod
    def from_prior(cls, state: LiveMatchState, prior: dict | None = None) -> "BasketballLivePosterior":
        prior = prior or {}
        current_home, current_away = float(state.home_score or 0), float(state.away_score or 0)
        elapsed, total_duration, remaining, rules_known = _clock_context(state)
        regulation_duration = get_settings().basketball_period_minutes * get_settings().basketball_regulation_periods * 60
        fraction = max(0.0, min(1.0, remaining / max(1.0, regulation_duration)))
        prior_home = float(prior.get("expected_home_score", 105.0)); prior_away = float(prior.get("expected_away_score", 102.0))
        prior_total = prior_home + prior_away
        current_total = current_home + current_away
        observed_rate = current_total / max(60.0, elapsed) * 60.0
        prior_rate = prior_total / max(60.0, regulation_duration) * 60.0
        evidence_weight = min(.8, max(.15, elapsed / max(60.0, regulation_duration))) if elapsed else .15
        remaining_rate = prior_rate * (1 - evidence_weight) + observed_rate * evidence_weight if elapsed else prior_rate
        expected_total = current_total + remaining_rate * (remaining / 60.0)
        prior_margin = prior_home - prior_away
        current_margin = current_home - current_away
        expected_margin = current_margin + prior_margin * fraction
        expected_home = (expected_total + expected_margin) / 2
        expected_away = (expected_total - expected_margin) / 2
        margin_sd = max(4.0, float(prior.get("margin_sd", 12.0)) * math.sqrt(max(.08, min(1.0, remaining / max(1.0, regulation_duration)))))
        total_sd = max(6.0, float(prior.get("total_sd", 18.0)) * math.sqrt(max(.08, min(1.0, remaining / max(1.0, regulation_duration)))))
        live = {"home_moneyline": float(norm.cdf(expected_margin / margin_sd)), "away_moneyline": float(norm.cdf(-expected_margin / margin_sd))}
        pre = {key: float(prior[key]) for key in ("home_moneyline", "away_moneyline") if isinstance(prior.get(key), (int, float))}
        if len(pre) != 2:
            pre = {"home_moneyline": float(norm.cdf(prior_margin / max(4.0, float(prior.get("margin_sd", 12.0))))), "away_moneyline": float(norm.cdf(-prior_margin / max(4.0, float(prior.get("margin_sd", 12.0)))))}
        evidence = _clamp(elapsed / max(1.0, regulation_duration)) * (.75 if rules_known else .55)
        return cls(state, expected_home, expected_away, margin_sd, total_sd, pre, live, evidence, bool(prior))

    def probabilities_for_market(self, market) -> dict:
        family, line, selection = market.market_family, float(market.line) if market.line is not None else None, market.selection
        margin = self.expected_home_score - self.expected_away_score; total = self.expected_home_score + self.expected_away_score
        margin_values, margin_probabilities = _discrete_normal(margin, self.margin_sd, low=-250, high=250)
        total_values, total_probabilities = _discrete_normal(total, self.total_sd, low=0, high=300)
        if family == "moneyline": win = margin_probabilities[margin_values > 0].sum() if selection == "home" else margin_probabilities[margin_values < 0].sum(); push = margin_probabilities[margin_values == 0].sum()
        elif family in {"spread", "handicap"}:
            adjusted = margin_values + line if market.participant == "home" else -margin_values + line; win = margin_probabilities[adjusted > 0].sum(); push = margin_probabilities[adjusted == 0].sum() if line is not None and line.is_integer() else 0.0
        elif family in {"game_total", "totals"}:
            win = total_probabilities[total_values > line].sum() if selection == "over" else total_probabilities[total_values < line].sum(); push = total_probabilities[total_values == line].sum() if line is not None and line.is_integer() else 0.0
        elif family == "team_total":
            score = self.expected_home_score if market.participant == "home" else self.expected_away_score; sd = self.total_sd / math.sqrt(2); score_values, score_probabilities = _discrete_normal(score, sd, low=0, high=200); win = score_probabilities[score_values > line].sum() if selection == "over" else score_probabilities[score_values < line].sum(); push = score_probabilities[score_values == line].sum() if line is not None and line.is_integer() else 0.0
        else: return {"status": "UNSUPPORTED", "reason": "live basketball market is not supported"}
        win, push = _clamp(float(win)), _clamp(float(push), 0.0, 1.0 - _clamp(float(win)))
        return {"status": "SUPPORTED", "win_probability": win, "push_probability": push, "loss_probability": max(0.0, 1.0 - win - push), "calibration_status": "PARTIALLY_CALIBRATED" if self.prior_was_observed else "UNCALIBRATED"}
