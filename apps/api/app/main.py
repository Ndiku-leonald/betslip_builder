import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.freshness import data_age_seconds
from app.models import Competition, Fixture, ProviderHealth, ProviderUsage, Sport, Team
from app.providers.api_sports import ApiSportsProvider, ProviderError
from app.quota import QuotaManager
from app.schemas import DetailOut, FixtureOut, ProviderStatus, ProviderUsageOut
from app.services.ingestion import ingest_fixtures

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()
quota = QuotaManager(settings.quota_mode)
football = ApiSportsProvider(name="api-football", key=settings.api_football_key, base_url="https://v3.football.api-sports.io", cache=cache, quota=quota)
basketball = ApiSportsProvider(name="api-basketball", key=settings.api_basketball_key, base_url="https://v1.basketball.api-sports.io", cache=cache, quota=quota)
providers = {"football": football, "basketball": basketball}
scheduler: AsyncIOScheduler | None = None
app_timezone = ZoneInfo(settings.app_timezone)


def _app_today() -> date:
    return datetime.now(app_timezone).date()


def _as_app_date(value: datetime) -> date:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(app_timezone).date()


def _app_day_start_utc() -> datetime:
    return datetime.combine(_app_today(), datetime.min.time(), tzinfo=app_timezone).astimezone(timezone.utc)


def _record_usage(provider: ApiSportsProvider, endpoint: str, *, status_code: int | None, error: str | None = None) -> None:
    with SessionLocal() as db:
        recorded_at = datetime.now(timezone.utc)
        effective_status = status_code if status_code is not None else provider.last_status_code
        usage = ProviderUsage(provider=provider.name, endpoint=endpoint, requested_at=recorded_at, status_code=effective_status, latency_ms=provider.last_latency_ms, cache_hit=provider.last_cache_hit, rate_limit_remaining=provider.last_rate_limit_remaining, error=error)
        db.add(usage)
        db.flush()
        health = db.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider.name))
        if health is None:
            health = ProviderHealth(provider=provider.name, configured=provider.configured, healthy=False)
            db.add(health)
        health.configured = provider.configured
        health.last_latency_ms = provider.last_latency_ms
        if not provider.last_cache_hit:
            if error or effective_status is None or effective_status >= 400:
                health.healthy = False
                health.last_error = error or provider.last_error or f"Provider returned HTTP {effective_status}"
            else:
                health.healthy = True
                health.last_success_at = recorded_at
                health.last_error = None
        health.calls_today = int(db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= _app_day_start_utc(), ProviderUsage.cache_hit.is_(False))) or 0)
        db.commit()


async def _scheduled_today(sport: str) -> None:
    provider = providers[sport]
    if not provider.configured:
        return
    try:
        items = await provider.fixtures_by_date(_app_today().isoformat())
        with SessionLocal() as db:
            ingest_fixtures(db, items)
        _record_usage(provider, "scheduled/fixtures", status_code=200)
    except ProviderError as exc:
        _record_usage(provider, "scheduled/fixtures", status_code=exc.status_code, error=str(exc))


async def _scheduled_live(sport: str) -> None:
    provider = providers[sport]
    if not provider.configured:
        return
    try:
        items = await provider.live_fixtures()
        with SessionLocal() as db:
            ingest_fixtures(db, items)
        _record_usage(provider, "scheduled/live", status_code=200)
    except ProviderError as exc:
        _record_usage(provider, "scheduled/live", status_code=exc.status_code, error=str(exc))


async def start_scheduler() -> None:
    global scheduler
    if settings.enable_scheduled_ingestion:
        if scheduler is not None and scheduler.running:
            return
        scheduler = AsyncIOScheduler(timezone=settings.app_timezone)
        scheduler.add_job(_scheduled_today, "interval", minutes=settings.prematch_refresh_minutes, args=["football"], id="football-today", replace_existing=True)
        scheduler.add_job(_scheduled_today, "interval", minutes=settings.prematch_refresh_minutes, args=["basketball"], id="basketball-today", replace_existing=True)
        if settings.quota_mode != "free":
            scheduler.add_job(_scheduled_live, "interval", seconds=settings.live_poll_seconds, args=["football"], id="football-live", replace_existing=True)
            scheduler.add_job(_scheduled_live, "interval", seconds=settings.live_poll_seconds, args=["basketball"], id="basketball-live", replace_existing=True)
        scheduler.start()


async def stop_scheduler() -> None:
    global scheduler
    if scheduler is not None:
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(title="SlipIQ API", version="0.1.0", description="Normalized sports data foundation; no predictions or bet placement.", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["*"])


def _fixture_out(db: Session, fixture: Fixture) -> FixtureOut:
    sport = db.scalar(select(Sport).where(Sport.id == fixture.sport_id))
    competition = db.scalar(select(Competition).where(Competition.id == fixture.competition_id)) if fixture.competition_id else None
    home = db.scalar(select(Team).where(Team.id == fixture.home_team_id))
    away = db.scalar(select(Team).where(Team.id == fixture.away_team_id))
    return FixtureOut(
        id=fixture.id, sport=sport.slug if sport else "unknown", competition=competition.name if competition else None,
        home=home.name if home else "Unknown", away=away.name if away else "Unknown", kickoff_at=fixture.kickoff_at,
        status=fixture.status, status_detail=fixture.status_detail, home_score=fixture.home_score, away_score=fixture.away_score,
        period=fixture.period, clock=fixture.clock, provider=fixture.provider, provider_timestamp=fixture.provider_timestamp,
        ingested_at=fixture.ingested_at, freshness=fixture.freshness,
        data_age_seconds=data_age_seconds(fixture.provider_timestamp),
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "slipiq-api", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/api/sports")
def sports(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "slug": item.slug, "name": item.name} for item in db.scalars(select(Sport).order_by(Sport.name))]


@app.get("/api/competitions")
def competitions(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "name": item.name, "sport_id": item.sport_id, "country_id": item.country_id} for item in db.scalars(select(Competition).order_by(Competition.name))]


def _fixtures(db: Session, sport: str | None = None, status: str | tuple[str, ...] | None = None, limit: int = 100) -> list[FixtureOut]:
    query = select(Fixture).order_by(Fixture.kickoff_at).limit(limit)
    if sport in providers:
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
        if sport_id:
            query = query.where(Fixture.sport_id == sport_id)
    if isinstance(status, tuple):
        query = query.where(Fixture.status.in_(status))
    elif status:
        query = query.where(Fixture.status == status)
    return [_fixture_out(db, fixture) for fixture in db.scalars(query)]


@app.get("/api/fixtures", response_model=list[FixtureOut])
def fixtures(sport: str | None = Query(default=None), status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport=sport, status=status, limit=limit)


@app.get("/api/fixtures/today", response_model=list[FixtureOut])
def fixtures_today(sport: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    today = _app_today()
    return [item for item in _fixtures(db, sport=sport, limit=limit) if item.kickoff_at and _as_app_date(item.kickoff_at) == today]


@app.get("/api/fixtures/live", response_model=list[FixtureOut])
def fixtures_live(sport: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport=sport, status=("live", "halftime"), limit=limit)


@app.get("/api/games/basketball", response_model=list[FixtureOut])
def basketball_games(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport="basketball", limit=limit)


@app.get("/api/games/basketball/live", response_model=list[FixtureOut])
def basketball_live(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport="basketball", status=("live", "halftime"), limit=limit)


@app.get("/api/fixtures/{fixture_id}", response_model=FixtureOut)
def fixture(fixture_id: str, db: Session = Depends(get_db)) -> FixtureOut:
    item = db.get(Fixture, fixture_id)
    if not item:
        raise HTTPException(404, "Fixture not found")
    return _fixture_out(db, item)


async def _detail(fixture_id: str, kind: str, db: Session) -> DetailOut:
    item = db.get(Fixture, fixture_id)
    if not item:
        raise HTTPException(404, "Fixture not found")
    provider = providers.get(db.scalar(select(Sport.slug).where(Sport.id == item.sport_id)))
    if not provider or not provider.configured:
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, message="Provider not configured")
    try:
        payload = await provider.fixture_details(item.provider_fixture_id)
        _record_usage(provider, f"details/{item.provider_fixture_id}", status_code=200)
        response = payload.get("response", [])
        data = response[0].get(kind) if response and isinstance(response[0], dict) else response
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=data is not None, data=data, stale=False, message=None if data is not None else "Not available from current provider")
    except ProviderError as exc:
        _record_usage(provider, f"details/{item.provider_fixture_id}", status_code=exc.status_code, error=str(exc))
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, stale=True, message=str(exc))


@app.get("/api/fixtures/{fixture_id}/stats", response_model=DetailOut)
async def fixture_stats(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "statistics", db)


@app.get("/api/fixtures/{fixture_id}/events", response_model=DetailOut)
async def fixture_events(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "events", db)


@app.get("/api/fixtures/{fixture_id}/lineups", response_model=DetailOut)
async def fixture_lineups(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "lineups", db)


@app.get("/api/providers/status", response_model=list[ProviderStatus])
def provider_status(db: Session = Depends(get_db)) -> list[ProviderStatus]:
    result = []
    for provider in providers.values():
        health = db.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider.name))
        if health is not None:
            result.append(ProviderStatus(provider=provider.name, configured=provider.configured, healthy=provider.configured and health.healthy, last_success_at=health.last_success_at, last_error=health.last_error, latency_ms=health.last_latency_ms, calls_today=health.calls_today))
            continue
        day_start = _app_day_start_utc()
        usage = list(db.scalars(select(ProviderUsage).where(ProviderUsage.provider == provider.name).order_by(ProviderUsage.requested_at.desc()).limit(100)))
        successful = next((item for item in usage if item.status_code is not None and item.status_code < 400 and not item.error), None)
        latest = usage[0] if usage else None
        calls_today = db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= day_start, ProviderUsage.cache_hit.is_(False))) or 0
        result.append(ProviderStatus(provider=provider.name, configured=provider.configured, healthy=bool(successful and (latest is None or not latest.error)), last_success_at=successful.requested_at if successful else provider.last_success_at, last_error=latest.error if latest and latest.error else provider.last_error, latency_ms=latest.latency_ms if latest else provider.last_latency_ms, calls_today=int(calls_today)))
    return result


@app.get("/api/provider-usage", response_model=list[ProviderUsageOut])
def provider_usage(db: Session = Depends(get_db)) -> list[ProviderUsageOut]:
    today_start = _app_day_start_utc()
    result = []
    for provider in providers.values():
        count = db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= today_start, ProviderUsage.cache_hit.is_(False))) or 0
        result.append(ProviderUsageOut(provider=provider.name, calls_today=int(count), mode=settings.quota_mode))
    return result


@app.post("/api/ingestion/today")
async def ingest_today(sport: str = Query(..., pattern="^(football|basketball)$"), db: Session = Depends(get_db)) -> dict:
    provider = providers[sport]
    date = _app_today().isoformat()
    try:
        items = await provider.fixtures_by_date(date)
    except ProviderError as exc:
        _record_usage(provider, "fixtures", status_code=exc.status_code, error=str(exc))
        raise HTTPException(503, {"code": "provider_error", "provider": exc.provider, "message": str(exc)}) from exc
    _record_usage(provider, "fixtures", status_code=200)
    return {"sport": sport, "date": date, "upserted": ingest_fixtures(db, items), "provider": provider.name}


@app.post("/api/ingestion/live")
async def ingest_live(sport: str = Query(..., pattern="^(football|basketball)$"), db: Session = Depends(get_db)) -> dict:
    provider = providers[sport]
    try:
        items = await provider.live_fixtures()
    except ProviderError as exc:
        _record_usage(provider, "live", status_code=exc.status_code, error=str(exc))
        raise HTTPException(503, {"code": "provider_error", "provider": exc.provider, "message": str(exc)}) from exc
    _record_usage(provider, "live", status_code=200)
    return {"sport": sport, "upserted": ingest_fixtures(db, items), "provider": provider.name}
