from __future__ import annotations

from enum import StrEnum


class CorrelationRisk(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CONFLICTING = "CONFLICTING"
    UNKNOWN = "UNKNOWN"


def _outcome_key(candidate: dict) -> tuple[str, str, str | None]:
    return (str(candidate.get("market_family", "")), str(candidate.get("selection", "")), candidate.get("participant"))


def classify_correlation(left: dict, right: dict) -> dict:
    """Return a transparent classification, not a fabricated covariance estimate."""
    if left.get("fixture_id") == right.get("fixture_id"):
        family_a, selection_a, participant_a = _outcome_key(left)
        family_b, selection_b, participant_b = _outcome_key(right)
        contradictory = (
            family_a in {"1x2", "moneyline", "handicap", "spread"} and family_b in {"1x2", "moneyline", "handicap", "spread"}
            and participant_a == participant_b and selection_a != selection_b
        ) or (family_a in {"totals", "game_total"} and family_b in {"totals", "game_total"} and selection_a != selection_b)
        return {"risk": CorrelationRisk.CONFLICTING.value if contradictory else CorrelationRisk.HIGH.value, "reason": "same fixture markets are dependent; same-fixture parlays are not validated"}
    teams_a = set(left.get("team_ids", []))
    teams_b = set(right.get("team_ids", []))
    if teams_a.intersection(teams_b):
        return {"risk": CorrelationRisk.HIGH.value, "reason": "the same team appears in multiple fixtures"}
    if left.get("competition_id") and left.get("competition_id") == right.get("competition_id"):
        return {"risk": CorrelationRisk.MODERATE.value, "reason": "same competition concentration"}
    if left.get("sport") == right.get("sport") and left.get("kickoff_at") and right.get("kickoff_at"):
        try:
            seconds = abs((left["kickoff_at"] - right["kickoff_at"]).total_seconds())
            if seconds <= 3 * 3600:
                return {"risk": CorrelationRisk.MODERATE.value, "reason": "same sport and close start window"}
        except (AttributeError, TypeError):
            return {"risk": CorrelationRisk.UNKNOWN.value, "reason": "start-time context was not comparable"}
    return {"risk": CorrelationRisk.LOW.value, "reason": "no known shared fixture, team, competition, or close sport window"}


def aggregate_correlation(legs: list[dict]) -> dict:
    risks = [classify_correlation(a, b) for index, a in enumerate(legs) for b in legs[index + 1:]]
    labels = [item["risk"] for item in risks]
    if CorrelationRisk.CONFLICTING.value in labels:
        overall = CorrelationRisk.CONFLICTING.value
    elif CorrelationRisk.HIGH.value in labels:
        overall = CorrelationRisk.HIGH.value
    elif CorrelationRisk.MODERATE.value in labels:
        overall = CorrelationRisk.MODERATE.value
    elif risks:
        overall = CorrelationRisk.LOW.value
    else:
        overall = CorrelationRisk.LOW.value
    return {"risk": overall, "pairs": risks, "unknown_pairs": labels.count(CorrelationRisk.UNKNOWN.value)}
