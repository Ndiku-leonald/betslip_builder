"""Conservative canonical fixture matching across provider identifiers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any


def normalize_team_name(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _time_distance(left: datetime | None, right: datetime | None) -> float | None:
    if left is None or right is None:
        return None
    if left.tzinfo is None:
        left = left.replace(tzinfo=right.tzinfo)
    if right.tzinfo is None:
        right = right.replace(tzinfo=left.tzinfo)
    return abs((left - right).total_seconds())


def match_fixture(candidate: dict[str, Any], known: list[dict[str, Any]], *, kickoff_tolerance_seconds: int = 18 * 3600) -> dict[str, Any]:
    """Return a match only when identity signals agree.

    Exact normalized home/away names are required. Competition and kickoff are
    corroborating signals; ties and weak name matches are returned as ambiguous.
    """
    home = normalize_team_name(candidate.get("home"))
    away = normalize_team_name(candidate.get("away"))
    if not home or not away:
        return {"status": "ambiguous", "confidence": 0.0, "matches": []}
    matches: list[dict[str, Any]] = []
    for item in known:
        if normalize_team_name(item.get("home")) != home or normalize_team_name(item.get("away")) != away:
            continue
        distance = _time_distance(candidate.get("kickoff_at"), item.get("kickoff_at"))
        if distance is not None and distance > kickoff_tolerance_seconds:
            continue
        competition_match = bool(candidate.get("competition") and item.get("competition") and normalize_team_name(candidate.get("competition")) == normalize_team_name(item.get("competition")))
        signals = 2 + int(competition_match) + int(distance is not None and distance <= 3600)
        matches.append({"item": item, "score": signals, "kickoff_distance_seconds": distance, "competition_match": competition_match})
    matches.sort(key=lambda value: value["score"], reverse=True)
    if not matches or (len(matches) > 1 and matches[0]["score"] == matches[1]["score"]):
        return {"status": "ambiguous", "confidence": 0.0, "matches": matches}
    confidence = min(1.0, matches[0]["score"] / 4)
    return {"status": "matched" if confidence >= 0.75 else "ambiguous", "confidence": confidence, "match": matches[0]["item"], "matches": matches}
