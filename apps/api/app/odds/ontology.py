from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
import re
from typing import Any


VALID_STATUSES = {"open", "suspended", "closed", "settled", "unavailable", "unknown"}
VALID_PARTICIPANTS = {"home", "away", "none"}
VALID_SELECTIONS = {"home", "away", "draw", "over", "under", "yes", "no", "win", "unknown"}


def decimal_odds(value: Any, format: str = "decimal") -> float:
    if value is None:
        raise ValueError("odds are required")
    if format == "decimal":
        result = float(value)
    elif format == "american":
        american = float(value)
        if american == 0: raise ValueError("American odds cannot be zero")
        result = 1 + american / 100 if american > 0 else 1 + 100 / abs(american)
    elif format == "fractional":
        result = 1 + float(Fraction(str(value)))
    else:
        raise ValueError(f"unsupported odds format: {format}")
    if result <= 1:
        raise ValueError("decimal odds must be greater than 1")
    return result


@dataclass(frozen=True)
class NormalizedMarket:
    fixture_id: str
    sport: str
    bookmaker: str
    provider: str
    market_family: str
    market_type: str
    period: str
    selection: str
    line: float | None
    decimal_odds: float | None
    status: str = "open"
    settlement_semantics: str = "full_game"
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    provider_updated_at: datetime | None = None
    source_event_id: str | None = None
    participant: str = "none"
    raw: dict[str, Any] | None = None

    def __post_init__(self):
        if self.status not in VALID_STATUSES: raise ValueError(f"invalid market status: {self.status}")
        if self.participant not in VALID_PARTICIPANTS: raise ValueError(f"invalid market participant: {self.participant}")
        if self.selection not in VALID_SELECTIONS: raise ValueError(f"invalid normalized selection: {self.selection}")
        if self.participant != "none" and self.selection in {"home", "away", "draw", "yes", "no"}:
            raise ValueError("participant and selection must not duplicate outcome semantics")
        if self.decimal_odds is not None and self.decimal_odds <= 1: raise ValueError("decimal odds must be greater than 1")

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        for key in ("observed_at", "provider_updated_at"):
            if result[key] is not None: result[key] = result[key].isoformat()
        return result


def _selection(name: str, family: str, sport: str) -> str:
    value = " ".join(str(name).lower().replace("_", " ").split())
    if value in {"home", "home team", "1", "team 1"}: return "home"
    if value in {"away", "away team", "2", "team 2"}: return "away"
    if value in {"draw", "x", "tie"}: return "draw"
    if value in {"yes", "y"}: return "yes"
    if value in {"no", "n"}: return "no"
    if value.startswith("over"): return "over"
    if value.startswith("under"): return "under"
    if family in {"handicap", "spread"}: return "win"
    return value


def extract_line(text: Any) -> float | None:
    """Extract only a line attached to an O/U, total, spread, or handicap label."""
    value = str(text or "")
    if not re.search(r"(?:over|under|total|spread|handicap|points?|goals?)", value, re.IGNORECASE):
        return None
    match = re.search(r"(?:over|under|total|spread|handicap|points?|goals?)[^+\-\d]{0,8}([+\-]?\d+(?:\.\d+)?)", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def normalize_external_market(*, fixture_id: str, sport: str, provider: str, bookmaker: str, market_name: str, selection_name: str, odds: Any, line: float | None = None, odds_format: str = "decimal", period: str = "full_game", participant: str | None = None, settlement_semantics: str | None = None, status: str = "open", observed_at: datetime | None = None, provider_updated_at: datetime | None = None, source_event_id: str | None = None, raw: dict[str, Any] | None = None) -> NormalizedMarket:
    label = " ".join(str(market_name).lower().replace("_", " ").split())
    sport = sport.lower()
    if any(token in label for token in ("match winner", "full time result", "1x2", "h2h", "moneyline", "winner")):
        family, market_type = (("moneyline", "moneyline") if sport == "basketball" and ("moneyline" in label or "h2h" in label) else ("1x2", "1x2"))
    elif "both" in label or "btts" in label:
        family, market_type = "btts", "btts"
    elif "spread" in label or "handicap" in label:
        family, market_type = "spread" if sport == "basketball" else "handicap", "spread" if sport == "basketball" else "handicap"
    elif "team total" in label or ("total" in label and re.search(r"\b(home|away)\b.*\b(team|total)\b|\b(team|total)\b.*\b(home|away)\b", label)):
        family, market_type = "team_total", "team_total"
    elif "total" in label or "over/under" in label or label.startswith(("over", "under")):
        family, market_type = ("game_total", "game_total") if sport == "basketball" else ("totals", "total_goals")
    else:
        family, market_type = "unknown", "unknown"
    if settlement_semantics is None:
        settlement_semantics = "regulation" if "regulation" in label else "including_overtime" if sport == "basketball" and family == "moneyline" else "full_game"
    if family == "1x2" and settlement_semantics not in {"full_game", "regulation"}:
        settlement_semantics = "full_game"
    if line is None:
        line = extract_line(selection_name) or extract_line(market_name)
    normalized_participant = participant or "none"
    normalized_selection = _selection(selection_name, family, sport)
    if family in {"team_total"}:
        if normalized_participant == "none":
            lowered = str(selection_name).lower()
            normalized_participant = "home" if "home" in lowered else "away" if "away" in lowered else "none"
        normalized_selection = "over" if str(selection_name).lower().startswith("over") else "under" if str(selection_name).lower().startswith("under") else normalized_selection
    if family in {"handicap", "spread"}:
        normalized_selection = "win"
    return NormalizedMarket(fixture_id=str(fixture_id), sport=sport, bookmaker=str(bookmaker), provider=provider, market_family=family, market_type=market_type, period=period, participant=normalized_participant, selection=normalized_selection, line=float(line) if line is not None else None, decimal_odds=decimal_odds(odds, odds_format) if status == "open" else None, status=status, settlement_semantics=settlement_semantics, observed_at=observed_at or datetime.now(timezone.utc), provider_updated_at=provider_updated_at, source_event_id=source_event_id, raw=raw or {})
