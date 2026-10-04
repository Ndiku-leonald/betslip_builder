"""Bounded, real-provider staging bootstrap orchestration.

This module deliberately contains orchestration only. Provider HTTP, quota
reservation, normalization, persistence, feature generation, and odds
matching remain owned by their existing modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.features.basketball import BasketballFeatureEngine
from app.features.football import FootballFeatureEngine
from app.features.common import persist_features
from app.historical.ingest import store_statistics
from app.markets.storage import persist_market_snapshots
from app.models import Competition, Fixture, FixtureFeatureSnapshot, Sport, Team
from app.odds.providers import OddsApiError, TheOddsApiProvider, parse_the_odds_api
from app.providers.api_sports import ApiSportsProvider, ProviderError, _parse_dt
from app.providers.matching import match_fixture
from app.services.ingestion import ingest_fixtures


MAX_LOOKBACK_DAYS = 7
MAX_LOOKAHEAD_DAYS = 7
MAX_STATISTICS_FIXTURES = 5
MAX_DAILY_FIXTURE_REQUESTS = MAX_LOOKBACK_DAYS + MAX_LOOKAHEAD_DAYS + 1


@dataclass(frozen=True)
class BootstrapScope:
    sport: str = "football"
    competition: str | None = "39"
    lookback_days: int = 3
    lookahead_days: int = 7
    include_statistics: bool = True
    include_odds: bool = True


@dataclass
class BootstrapResult:
    status: str = "completed"
    sport: str = "football"
    scope: dict[str, Any] = field(default_factory=dict)
    providers_attempted: list[str] = field(default_factory=list)
    providers_succeeded: list[str] = field(default_factory=list)
    providers_unavailable: list[dict[str, str]] = field(default_factory=list)
    provider_state: str | None = None
    provider_reason_code: str | None = None
    provider_diagnostic: dict[str, Any] | None = None
    competitions_written: int = 0
    teams_written: int = 0
    fixtures_written: int = 0
    statistics_written: int = 0
    features_written: int = 0
    odds_written: int = 0
    matched_odds_events: int = 0
    unresolved_odds_events: int = 0
    ambiguous_odds_events: int = 0
    external_requests: int = 0
    warnings: list[str] = field(default_factory=list)
    error_category: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "sport": self.sport,
            "scope": self.scope,
            "providers_attempted": self.providers_attempted,
            "providers_succeeded": self.providers_succeeded,
            "providers_unavailable": self.providers_unavailable,
            "provider_state": self.provider_state,
            "provider_reason_code": self.provider_reason_code,
            "provider_diagnostic": self.provider_diagnostic,
            "competitions_written": self.competitions_written,
            "teams_written": self.teams_written,
            "fixtures_written": self.fixtures_written,
            "statistics_written": self.statistics_written,
            "features_written": self.features_written,
            "odds_written": self.odds_written,
            "matched_odds_events": self.matched_odds_events,
            "unresolved_odds_events": self.unresolved_odds_events,
            "ambiguous_odds_events": self.ambiguous_odds_events,
            "external_requests": self.external_requests,
            "warnings": self.warnings,
            "error_category": self.error_category,
        }


def provider_state(*, configured: bool, status_code: int | None = None, error: str | None = None, category: str | None = None) -> str:
    if not configured:
        return "missing"
    if category:
        return category
    text = (error or "").casefold()
    for category_name in ("plan_restricted", "entitlement_unavailable", "quota_exhausted", "rate_limited", "temporarily_unavailable", "no_data"):
        if category_name in text:
            return category_name
    if status_code == 401:
        return "authentication_failed"
    if status_code == 400:
        return "invalid_parameter"
    if status_code == 403:
        return "entitlement_unavailable"
    if status_code == 429:
        return "quota_exhausted" if error and "quota" in error.lower() else "rate_limited"
    if status_code is not None and status_code >= 500:
        return "temporarily_unavailable"
    if error:
        return "error"
    if status_code is not None and status_code < 400:
        return "healthy"
    return "unknown"


def _count(db: Session, model: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def _date_range(scope: BootstrapScope, today: date) -> list[str]:
    start = today - timedelta(days=scope.lookback_days)
    end = today + timedelta(days=scope.lookahead_days)
    return [(start + timedelta(days=offset)).isoformat() for offset in range((end - start).days + 1)]


def _is_terminal_provider_error(exc: ProviderError) -> bool:
    return exc.terminal or exc.status_code in {401, 403, 429}


def _odds_sport_key(scope: BootstrapScope) -> str | None:
    # The Odds API uses its own sport taxonomy.  Do not guess arbitrary keys.
    if scope.sport == "football" and (scope.competition or "").casefold() in {"39", "epl", "premier league", "soccer_epl"}:
        return "soccer_epl"
    return None


async def run_bootstrap(
    db: Session,
    scope: BootstrapScope,
    *,
    provider: ApiSportsProvider,
    odds_provider: TheOddsApiProvider | None,
    record_provider_event: Callable[[Any, str, int | None, str | None], None],
) -> BootstrapResult:
    result = BootstrapResult(sport=scope.sport, scope={
        "competition": scope.competition,
        "lookback_days": scope.lookback_days,
        "lookahead_days": scope.lookahead_days,
        "include_statistics": scope.include_statistics,
        "include_odds": scope.include_odds,
        "max_fixture_requests": MAX_DAILY_FIXTURE_REQUESTS,
        "max_statistics_fixtures": MAX_STATISTICS_FIXTURES,
    })
    result.providers_attempted.append(provider.name)
    if not provider.configured:
        result.status = "failed"
        result.error_category = "missing"
        result.provider_state = "missing"
        result.provider_reason_code = "provider_not_configured"
        result.provider_diagnostic = {
            "provider": provider.name,
            "endpoint": "fixtures",
            "classification": "missing",
            "reason_code": "provider_not_configured",
            "error_key": "configuration",
            "status_code": None,
            "external_request": False,
            "terminal": True,
            "retryable": False,
        }
        result.providers_unavailable.append({"provider": provider.name, "state": "missing"})
        result.warnings.append("Primary provider credentials are not configured.")
        return result

    before = {model: _count(db, model) for model in (Competition, Team, Fixture)}
    items_by_id: dict[str, Any] = {}
    today = datetime.now(timezone.utc).date()
    dates = _date_range(scope, today)
    for day in dates:
        try:
            items = await provider.fixtures_by_date(day, league=scope.competition)
            result.external_requests += sum(1 for event in provider.last_request_events if event.get("external_request"))
            record_provider_event(provider, "bootstrap/fixtures", 200, None)
            for item in items:
                items_by_id[item.provider_fixture_id] = item
            if provider.name not in result.providers_succeeded:
                result.providers_succeeded.append(provider.name)
        except ProviderError as exc:
            result.external_requests += sum(1 for event in provider.last_request_events if event.get("external_request"))
            record_provider_event(provider, "bootstrap/fixtures", exc.status_code, str(exc))
            state = provider_state(configured=True, status_code=exc.status_code, error=str(exc), category=exc.category)
            result.provider_state = state
            result.provider_reason_code = exc.reason_code or "provider_error"
            result.provider_diagnostic = exc.diagnostic(endpoint=(provider.last_request_events[-1].get("endpoint") if provider.last_request_events else exc.endpoint))
            result.providers_unavailable.append({"provider": provider.name, "state": state})
            result.error_category = state
            result.warnings.append(f"{provider.name} unavailable during fixture ingestion ({state}).")
            if _is_terminal_provider_error(exc):
                break

    items = list(items_by_id.values())
    if items:
        result.fixtures_written = ingest_fixtures(db, items)
        result.competitions_written = max(0, _count(db, Competition) - before[Competition])
        result.teams_written = max(0, _count(db, Team) - before[Team])
    elif not result.providers_unavailable:
        result.warnings.append("Provider returned no fixtures for the bounded period.")
        result.provider_state = "no_data"

    if scope.include_statistics and items:
        stats_candidates = [item for item in items if item.status == "finished"][:MAX_STATISTICS_FIXTURES]
        for item in stats_candidates:
            fixture = db.scalar(select(Fixture).where(Fixture.provider == item.provider, Fixture.provider_fixture_id == item.provider_fixture_id))
            if fixture is None:
                continue
            try:
                payload = await provider.detail("stats", item.provider_fixture_id)
                result.external_requests += sum(1 for event in provider.last_request_events if event.get("external_request"))
                record_provider_event(provider, "bootstrap/statistics", 200, None)
                result.statistics_written += store_statistics(db, fixture, item, payload)
            except ProviderError as exc:
                result.external_requests += sum(1 for event in provider.last_request_events if event.get("external_request"))
                record_provider_event(provider, "bootstrap/statistics", exc.status_code, str(exc))
                state = provider_state(configured=True, status_code=exc.status_code, error=str(exc), category=exc.category)
                result.warnings.append(f"Statistics unavailable for one fixture ({state}); stored results remain valid.")
                if result.provider_diagnostic is None:
                    result.provider_reason_code = exc.reason_code or "provider_error"
                    result.provider_diagnostic = exc.diagnostic(endpoint=(provider.last_request_events[-1].get("endpoint") if provider.last_request_events else exc.endpoint))
                if _is_terminal_provider_error(exc):
                    break
        if not stats_candidates:
            result.warnings.append("No completed fixtures were available for bounded statistics collection.")

    if items:
        engine = FootballFeatureEngine() if scope.sport == "football" else BasketballFeatureEngine()
        rows = engine.build(db, include_unfinished=True)
        result.features_written = persist_features(db, rows, engine.feature_version)

    if scope.include_odds:
        await _ingest_odds(db, scope, odds_provider, result, record_provider_event)

    # A small staging bootstrap must never silently activate a production model.
    if not db.scalar(select(func.count()).select_from(FixtureFeatureSnapshot).where(FixtureFeatureSnapshot.sport == scope.sport)):
        result.warnings.append("No feature snapshots were generated from the bounded provider data.")
    result.warnings.append("Training and production prediction generation were not run; model promotion remains explicit and gated.")
    if result.error_category:
        result.status = "partial" if result.fixtures_written else "failed"
    return result


async def _ingest_odds(
    db: Session,
    scope: BootstrapScope,
    odds_provider: TheOddsApiProvider | None,
    result: BootstrapResult,
    record_provider_event: Callable[[Any, str, int | None, str | None], None],
) -> None:
    if odds_provider is None or not odds_provider.configured:
        result.providers_unavailable.append({"provider": "the-odds-api", "state": "missing"})
        result.warnings.append("The Odds API is not configured; odds ingestion was skipped.")
        return
    sport_key = _odds_sport_key(scope)
    if sport_key is None:
        result.warnings.append("No verified The Odds API sport mapping exists for this bootstrap scope; odds request skipped.")
        return
    now = datetime.now(timezone.utc)
    fixtures = list(db.scalars(select(Fixture).join(Sport, Sport.id == Fixture.sport_id).where(Sport.slug == scope.sport, Fixture.status == "scheduled", Fixture.kickoff_at >= now - timedelta(hours=1), Fixture.kickoff_at <= now + timedelta(days=scope.lookahead_days + 1))))
    if not fixtures:
        result.warnings.append("No canonical upcoming fixtures exist; The Odds API quota was preserved.")
        return
    result.providers_attempted.append(odds_provider.name)
    try:
        events = await odds_provider.list_events(sport_key)
        record_provider_event(odds_provider, f"bootstrap/odds/{sport_key}", 200, None)
        result.external_requests += 1 if not getattr(odds_provider, "last_cache_hit", False) else 0
    except OddsApiError as exc:
        record_provider_event(odds_provider, f"bootstrap/odds/{sport_key}", exc.status_code, str(exc))
        state = provider_state(configured=True, status_code=exc.status_code, error=str(exc))
        result.providers_unavailable.append({"provider": odds_provider.name, "state": state})
        result.warnings.append(f"The Odds API was unavailable ({state}); no odds were stored.")
        return
    result.providers_succeeded.append(odds_provider.name)
    known = [{"id": item.id, "home": _team_name(db, item.home_team_id), "away": _team_name(db, item.away_team_id), "competition": _competition_name(db, item.competition_id), "kickoff_at": item.kickoff_at} for item in fixtures]
    for event in events:
        candidate = {"home": event.get("home_team"), "away": event.get("away_team"), "competition": sport_key, "kickoff_at": _parse_dt(event.get("commence_time"))}
        matched = match_fixture(candidate, known)
        if matched["status"] == "ambiguous":
            result.ambiguous_odds_events += 1
            continue
        if matched["status"] != "matched":
            result.unresolved_odds_events += 1
            continue
        result.matched_odds_events += 1
        fixture_id = matched["match"]["id"]
        try:
            markets = parse_the_odds_api([event], fixture_id, scope.sport, odds_provider.name)
        except ValueError:
            result.ambiguous_odds_events += 1
            continue
        result.odds_written += persist_market_snapshots(db, markets, deduplicate=True)


def _team_name(db: Session, team_id: str) -> str | None:
    return db.scalar(select(Team.name).where(Team.id == team_id))


def _competition_name(db: Session, competition_id: str | None) -> str | None:
    return db.scalar(select(Competition.name).where(Competition.id == competition_id)) if competition_id else None
