from __future__ import annotations

from enum import StrEnum


class CorrelationRisk(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


def _family(candidate: dict) -> str:
    return str(candidate.get("market_family") or candidate.get("market_type") or "").lower()


def _selection(candidate: dict) -> str:
    return str(candidate.get("selection") or "").lower().replace(" ", "_")


def _participant(candidate: dict) -> str:
    return str(candidate.get("participant") or "").lower().replace(" ", "_")


def _line(candidate: dict) -> float | None:
    try:
        return float(candidate["line"]) if candidate.get("line") is not None else None
    except (TypeError, ValueError):
        return None


def _result_side(candidate: dict) -> str | None:
    selection, participant = _selection(candidate), _participant(candidate)
    if selection in {"home", "home_win", "team_a", "a"} or participant in {"home", "team_a", "a"}:
        return "home"
    if selection in {"away", "away_win", "team_b", "b"} or participant in {"away", "team_b", "b"}:
        return "away"
    if selection in {"draw", "tie"}:
        return "draw"
    return None


def _is_over(candidate: dict) -> bool:
    selection = _selection(candidate)
    return selection in {"over", "over_2.5", "over_3.5", "yes"} or "over" in selection


def _is_under(candidate: dict) -> bool:
    selection = _selection(candidate)
    return selection in {"under", "under_2.5", "under_3.5", "no"} or "under" in selection


def _same_line(left: dict, right: dict) -> bool:
    a, b = _line(left), _line(right)
    return a is not None and b is not None and abs(a - b) < 1e-9


def _same_handicap_line(left: dict, right: dict) -> bool:
    a, b = _line(left), _line(right)
    return a is not None and b is not None and abs(abs(a) - abs(b)) < 1e-9


def classify_correlation(left: dict, right: dict) -> dict:
    """Classify dependency using explicit market semantics; never invent coefficients."""
    if left.get("fixture_id") != right.get("fixture_id"):
        teams_a, teams_b = set(left.get("team_ids", [])), set(right.get("team_ids", []))
        if teams_a.intersection(teams_b):
            return {"risk": CorrelationRisk.HIGH.value, "reason": "the same team appears in multiple fixtures"}
        if left.get("competition_id") and left.get("competition_id") == right.get("competition_id"):
            return {"risk": CorrelationRisk.MODERATE.value, "reason": "same competition concentration"}
        if left.get("sport") == right.get("sport") and left.get("kickoff_at") and right.get("kickoff_at"):
            try:
                if abs((left["kickoff_at"] - right["kickoff_at"]).total_seconds()) <= 3 * 3600:
                    return {"risk": CorrelationRisk.MODERATE.value, "reason": "same sport and close start window"}
            except (AttributeError, TypeError):
                return {"risk": CorrelationRisk.UNKNOWN.value, "reason": "start-time context was not comparable"}
        return {"risk": CorrelationRisk.LOW.value, "reason": "no known shared fixture, team, competition, or close sport window"}

    fa, fb = _family(left), _family(right)
    sa, sb = _selection(left), _selection(right)
    result_families = {"1x2", "moneyline", "match_result", "draw_no_bet"}
    spread_families = {"handicap", "spread"}
    total_families = {"totals", "game_total", "total"}
    team_total_families = {"team_total", "team_totals"}
    if fa in result_families and fb in result_families and _result_side(left) and _result_side(right) and _result_side(left) != _result_side(right):
        return {"risk": CorrelationRisk.CONFLICTING.value, "reason": "opposing match-result sides on the same fixture"}
    if fa in total_families and fb in total_families and _same_line(left, right) and ((_is_over(left) and _is_under(right)) or (_is_under(left) and _is_over(right))):
        return {"risk": CorrelationRisk.CONFLICTING.value, "reason": "over and under on the same game total line"}
    if fa in team_total_families and fb in team_total_families and _participant(left) == _participant(right) and _same_line(left, right) and ((_is_over(left) and _is_under(right)) or (_is_under(left) and _is_over(right))):
        return {"risk": CorrelationRisk.CONFLICTING.value, "reason": "opposing team-total outcomes on the same line"}
    if fa in spread_families and fb in spread_families and _same_handicap_line(left, right) and _participant(left) != _participant(right):
        return {"risk": CorrelationRisk.CONFLICTING.value, "reason": "opposite handicap sides at the same line"}
    if (fa in result_families and fb in spread_families) or (fb in result_families and fa in spread_families):
        return {"risk": CorrelationRisk.HIGH.value, "reason": "match result and related handicap/spread on the same fixture are dependent"}
    if (fa in result_families and fb in result_families) or (fa in spread_families and fb in spread_families):
        return {"risk": CorrelationRisk.HIGH.value, "reason": "same-fixture result or spread markets are dependent"}
    if (fa in total_families and fb == "btts") or (fb in total_families and fa == "btts"):
        over_total = (fa in total_families and _is_over(left)) or (fb in total_families and _is_over(right))
        btts_yes = sa == "yes" if fb == "btts" else sb == "yes"
        if over_total == btts_yes:
            return {"risk": CorrelationRisk.HIGH.value, "reason": "game total and BTTS direction are dependent"}
    if (fa in team_total_families and fb in total_families) or (fb in team_total_families and fa in total_families):
        return {"risk": CorrelationRisk.HIGH.value, "reason": "team total and game total are dependent"}
    return {"risk": CorrelationRisk.HIGH.value, "reason": "same-fixture markets are dependent; same-game combinations are not validated"}


def aggregate_correlation(legs: list[dict]) -> dict:
    risks = [classify_correlation(a, b) for index, a in enumerate(legs) for b in legs[index + 1:]]
    labels = [item["risk"] for item in risks]
    if CorrelationRisk.CONFLICTING.value in labels:
        overall = CorrelationRisk.CONFLICTING.value
    elif CorrelationRisk.HIGH.value in labels:
        overall = CorrelationRisk.HIGH.value
    elif CorrelationRisk.MODERATE.value in labels:
        overall = CorrelationRisk.MODERATE.value
    else:
        overall = CorrelationRisk.LOW.value
    return {"risk": overall, "pairs": risks, "unknown_pairs": labels.count(CorrelationRisk.UNKNOWN.value)}
