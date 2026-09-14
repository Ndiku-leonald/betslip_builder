from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass
class NormalizedFixture:
    provider: str
    provider_fixture_id: str
    sport: str
    competition_name: str
    competition_provider_id: str | None
    country_name: str | None
    season_name: str | None
    home_provider_id: str
    home_name: str
    away_provider_id: str
    away_name: str
    kickoff_at: datetime | None
    status: str
    status_detail: str | None
    home_score: int | None
    away_score: int | None
    period: str | None
    clock: str | None
    provider_timestamp: datetime | None
    raw: dict[str, Any]


class SportsProvider(Protocol):
    name: str
    configured: bool

    async def fixtures_by_date(self, date: str) -> list[NormalizedFixture]: ...
    async def live_fixtures(self) -> list[NormalizedFixture]: ...
    async def fixture_details(self, provider_fixture_id: str) -> dict[str, Any]: ...

