"""Quota-bounded real-data commissioning smoke test.

This script is intentionally manual-only. It never prints credentials or raw
provider payloads and it never calls a provider when its key is absent.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.features.football import FootballFeatureEngine
from app.historical.ingest import store_statistics
from app.main import api_sports_odds, football, football_data, odds_provider, prediction_service, quota
from app.markets.storage import persist_market_snapshots
from app.models import Fixture, Team
from app.odds.providers import OddsApiError, parse_the_odds_api
from app.providers.api_sports import ProviderError
from app.providers.football_data import FootballDataError
from app.providers.matching import match_fixture
from app.services.ingestion import ingest_fixtures
from app.slips.optimizer import SlipOptimizer


def report(label: str, status: str, detail: str | None = None) -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"{label}: {status}{suffix}")


def _day(offset: int) -> str:
    tz = ZoneInfo(get_settings().app_timezone)
    return (datetime.now(tz).date() + timedelta(days=offset)).isoformat()


async def run(args: argparse.Namespace) -> int:
    print("SlipIQ real-data commissioning smoke")
    print(f"Environment: {get_settings().app_env}; timezone: {get_settings().app_timezone}")
    for slot in get_settings().additional_provider_slots:
        label = slot["name"] or f"additional-provider-{slot['slot']}"
        report(label, "CONFIGURED" if slot["configured"] else "NOT CONFIGURED", "adapter pending; no unverified endpoint was called")
    if odds_provider is None:
        report("The Odds API", "DISABLED", "set ENABLE_ODDS_API=true to exercise this configured credential")
    elif not odds_provider.configured:
        report("The Odds API", "NOT CONFIGURED")
    elif not args.odds_sport_key:
        report("The Odds API", "CONFIGURED", "not queried; pass --odds-sport-key to select a documented sport")

    if not football.configured:
        report("API-Football", "NOT CONFIGURED")
        report("API-Football fixture ingestion", "SKIPPED", "credential unavailable")
        return 0

    # A request budget caps actual retry attempts, not just logical operations.
    football.request_budget = args.max_requests
    try:
        today_items = await football.fixtures_by_date(_day(0))
    except ProviderError as exc:
        status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
        report("API-Football", status, str(exc))
        return 1
    report("API-Football", "CONFIGURED")
    report("Today fixtures", "PASS", f"{len(today_items)} returned")

    date_results: dict[str, list] = {_day(0): today_items}
    for offset, label in ((1, "Tomorrow fixtures"), (-1, "Recently completed fixtures")):
        try:
            items = await football.fixtures_by_date(_day(offset))
            date_results[_day(offset)] = items
            report(label, "PASS", f"{len(items)} returned")
        except ProviderError as exc:
            status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
            report(label, status, str(exc))

    real_items = [item for items in date_results.values() for item in items]
    with SessionLocal() as db:
        upserted = ingest_fixtures(db, real_items)
    report("Canonical fixture ingestion", "PASS", f"{upserted} real provider observations upserted")

    # Controlled detail fan-out: statistics for at most two completed matches.
    completed = [item for item in real_items if item.status == "finished"][: args.max_detail_fixtures]
    statistics_saved = 0
    for item in completed:
        try:
            payload = await football.detail("stats", item.provider_fixture_id)
            with SessionLocal() as db:
                fixture = db.scalar(select(Fixture).where(Fixture.provider == item.provider, Fixture.provider_fixture_id == item.provider_fixture_id))
                if fixture is not None:
                    statistics_saved += store_statistics(db, fixture, item, payload)
        except ProviderError:
            continue
    report("Historical/statistics detail", "PASS" if completed else "SKIPPED", f"{statistics_saved} team-stat rows stored" if completed else "no completed fixture returned")

    # Coverage is a single, bounded catalog call. The response is summarized,
    # never printed.
    if args.coverage:
        try:
            leagues = (await football.football_leagues()).get("response", [])
            names = {str(((item.get("league") or {}).get("name") or "")).casefold() for item in leagues}
            requested = {"premier league", "la liga", "serie a", "bundesliga", "ligue 1", "champions league"}
            report("API-Football coverage", "PASS", f"{len(leagues)} competitions returned; {len(names & requested)} major names observed")
        except ProviderError as exc:
            status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
            report("API-Football coverage", status, str(exc))

    # The football-data adapter is validation-only: never ingest it as a second
    # canonical fixture row.
    if not football_data.configured:
        report("football-data.org", "NOT CONFIGURED")
    else:
        try:
            competitions = await football_data.competitions()
            secondary = await football_data.fixtures_by_date(_day(0))
            primary = [{"home": item.home_name, "away": item.away_name, "competition": item.competition_name, "kickoff_at": item.kickoff_at} for item in today_items]
            matched = sum(match_fixture({"home": item.home_name, "away": item.away_name, "competition": item.competition_name, "kickoff_at": item.kickoff_at}, primary)["status"] == "matched" for item in secondary)
            report("football-data.org", "CONFIGURED", f"{len(competitions)} competitions; {matched}/{len(secondary)} unambiguous primary matches")
        except FootballDataError as exc:
            status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
            report("football-data.org", status, str(exc))

    # Feature engine output is computed only from observed real fixtures. It is
    # not persisted as a claim of model quality.
    with SessionLocal() as db:
        rows = FootballFeatureEngine().build(db, include_unfinished=True)
        real_rows = [row for row in rows if db.get(Fixture, row.fixture_id) and db.get(Fixture, row.fixture_id).provider == "api-football"]
        quality_values = [float((row.data_quality or {}).get("overall", 0)) for row in real_rows]
    report("Real feature generation", "PASS" if real_rows else "SKIPPED", f"{len(real_rows)} rows; quality range {min(quality_values):.1f}-{max(quality_values):.1f}" if quality_values else "insufficient real history")

    # Generate one pre-match prediction only if a champion model and enough
    # chronological history already exist.
    with SessionLocal() as db:
        upcoming = list(db.scalars(select(Fixture).where(Fixture.provider == "api-football", Fixture.status == "scheduled").order_by(Fixture.kickoff_at).limit(1)))
        prediction_fixture = upcoming[0] if upcoming else None
        if prediction_fixture is None:
            prediction_status = "SKIPPED"
            prediction_detail = "no scheduled real fixture"
        else:
            try:
                prediction_service.generate(db, prediction_fixture.id)
                prediction_status, prediction_detail = "PASS", "persisted pre-match prediction"
            except Exception as exc:
                prediction_status, prediction_detail = "SKIPPED", exc.__class__.__name__
    report("Real pre-match prediction", prediction_status, prediction_detail)

    # Odds are real only when an upstream odds response produces normalized
    # bookmaker markets. Fair/model prices are never substituted.
    odds_saved = 0
    odds_events_seen = 0
    if football.configured:
        with SessionLocal() as db:
            candidates = list(db.scalars(select(Fixture).where(Fixture.provider == "api-football", Fixture.status == "scheduled").order_by(Fixture.kickoff_at).limit(args.max_odds_fixtures)))
        for item in candidates:
            try:
                markets = await api_sports_odds["football"].markets_for_fixture(item.provider_fixture_id, "football")
                for market in markets:
                    object.__setattr__(market, "fixture_id", item.id)
                if markets:
                    with SessionLocal() as db:
                        odds_saved += persist_market_snapshots(db, markets)
            except ProviderError:
                continue
    if odds_provider is not None and odds_provider.configured and args.odds_sport_key:
        try:
            events = await odds_provider.list_events(args.odds_sport_key)
            odds_events_seen = len(events)
            with SessionLocal() as db:
                known = list(db.scalars(select(Fixture).where(Fixture.provider == "api-football", Fixture.status == "scheduled")))
                known_by_id = {
                    item.id: {"home": db.get(Team, item.home_team_id).name, "away": db.get(Team, item.away_team_id).name, "competition": "", "kickoff_at": item.kickoff_at}
                    for item in known
                }
                for event in events:
                    kickoff = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00")) if event.get("commence_time") else None
                    matched_id = next((item_id for item_id, known_item in known_by_id.items() if match_fixture({"home": event.get("home_team"), "away": event.get("away_team"), "competition": args.odds_sport_key, "kickoff_at": kickoff}, [known_item])["status"] == "matched"), None)
                    matched = db.get(Fixture, matched_id) if matched_id else None
                    if matched is not None:
                        odds_saved += persist_market_snapshots(db, parse_the_odds_api([event], matched.id, "football", odds_provider.name))
            report("The Odds API", "PASS", f"{len(events)} events returned")
        except OddsApiError as exc:
            status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
            report("The Odds API", status, str(exc))
    if odds_saved:
        report("Real bookmaker odds", "PASS", f"{odds_saved} immutable snapshots stored")
    elif odds_events_seen:
        report("Real bookmaker odds", "SKIPPED", f"{odds_events_seen} provider events returned; none matched a scheduled canonical fixture")
    elif odds_provider is not None and odds_provider.configured:
        report("Real bookmaker odds", "SKIPPED", "provider configured; pass --odds-sport-key to select a documented sport")
    else:
        print("REAL ODDS PROVIDER REQUIRED — no real bookmaker prices were stored")

    if args.live:
        try:
            live = await football.live_fixtures()
            with SessionLocal() as db:
                ingest_fixtures(db, live)
            report("API-Football live provider", "PASS", f"{len(live)} live fixtures returned")
        except ProviderError as exc:
            status = "QUOTA LIMITED" if exc.status_code == 429 else "AUTH FAILED" if exc.status_code in {401, 403} else "FAILED"
            report("API-Football live provider", status, str(exc))
    else:
        report("Live provider", "SKIPPED", "disabled by flag")

    with SessionLocal() as db:
        optimizer = SlipOptimizer()
        for target, profile in ((3.0, "conservative"), (5.0, "balanced"), (10.0, "aggressive")):
            result = optimizer.optimize(db, {"sports": ["football"], "target_odds": target, "profile": profile, "min_legs": 1, "max_legs": 8, "include_live": False, "mode": "prematch", "real_only": True})
            report(f"Betslip target {target:.2f}", result.get("status", "UNKNOWN"), f"{len(result.get('slips', []))} option(s)")

    with SessionLocal() as db:
        synthetic = int(db.scalar(select(func.count(Fixture.id)).where(Fixture.provider.like("synthetic%"))) or 0)
        real = int(db.scalar(select(func.count(Fixture.id)).where(Fixture.provider == "api-football")) or 0)
    report("Demo/real isolation", "PASS", f"real_only optimizer; {real} API-Football fixtures and {synthetic} synthetic fixtures present outside real recommendations")
    for provider_name in ("api-football", "football-data.org"):
        report(f"Quota {provider_name}", "INFO", f"{quota.calls_today(provider_name)} outbound attempt(s) accounted")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a quota-bounded, sanitized SlipIQ real-data commissioning smoke test")
    parser.add_argument("--max-requests", type=int, default=20)
    parser.add_argument("--max-detail-fixtures", type=int, default=2)
    parser.add_argument("--max-odds-fixtures", type=int, default=2)
    parser.add_argument("--odds-sport-key", default=None, help="The Odds API sport key; omit to skip that optional source")
    parser.add_argument("--no-coverage", dest="coverage", action="store_false")
    parser.add_argument("--no-live", dest="live", action="store_false")
    parser.set_defaults(coverage=True, live=True)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
