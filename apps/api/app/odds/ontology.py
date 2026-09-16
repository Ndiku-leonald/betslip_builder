from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any


VALID_STATUSES = {"open", "suspended", "closed", "settled", "unavailable"}


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
    raw: dict[str, Any] | None = None

    def __post_init__(self):
        if self.status not in VALID_STATUSES: raise ValueError(f"invalid market status: {self.status}")
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
    return value


def normalize_external_market(*, fixture_id: str, sport: str, provider: str, bookmaker: str, market_name: str, selection_name: str, odds: Any, line: float | None = None, odds_format: str = "decimal", period: str = "full_game", settlement_semantics: str | None = None, status: str = "open", observed_at: datetime | None = None, provider_updated_at: datetime | None = None, source_event_id: str | None = None, raw: dict[str, Any] | None = None) -> NormalizedMarket:
    label = " ".join(str(market_name).lower().replace("_", " ").split())
    sport = sport.lower()
    if any(token in label for token in ("match winner", "full time result", "1x2", "h2h", "moneyline", "winner")):
        family, market_type = (("moneyline", "moneyline") if sport == "basketball" and ("moneyline" in label or "h2h" in label) else ("1x2", "1x2"))
    elif "both" in label or "btts" in label:
        family, market_type = "btts", "btts"
    elif "spread" in label or "handicap" in label:
        family, market_type = "spread" if sport == "basketball" else "handicap", "spread" if sport == "basketball" else "handicap"
    elif "team total" in label:
        family, market_type = "team_total", "team_total"
    elif "total" in label or "over/under" in label or label.startswith(("over", "under")):
        family, market_type = ("game_total", "game_total") if sport == "basketball" else ("totals", "total_goals")
    else:
        family, market_type = "unknown", "unknown"
    if settlement_semantics is None:
        settlement_semantics = "regulation" if "regulation" in label else "including_overtime" if sport == "basketball" and family == "moneyline" else "full_game"
    if family == "1x2" and settlement_semantics not in {"full_game", "regulation"}:
        settlement_semantics = "full_game"
    return NormalizedMarket(fixture_id=str(fixture_id), sport=sport, bookmaker=str(bookmaker), provider=provider, market_family=family, market_type=market_type, period=period, selection=_selection(selection_name, family, sport), line=float(line) if line is not None else None, decimal_odds=decimal_odds(odds, odds_format) if status == "open" else None, status=status, settlement_semantics=settlement_semantics, observed_at=observed_at or datetime.now(timezone.utc), provider_updated_at=provider_updated_at, source_event_id=source_event_id, raw=raw or {})
