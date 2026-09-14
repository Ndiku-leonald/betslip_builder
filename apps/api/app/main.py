import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache import cache
from app.config import get_settings
from app.db import get_db
from app.freshness import data_age_seconds
from app.models import Competition, Fixture, ProviderUsage, Sport, Team
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

app = FastAPI(title="SlipIQ API", version="0.1.0", description="Normalized sports data foundation; no predictions or bet placement.")
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


def _fixtures(db: Session, sport: str | None = None, status: str | None = None, limit: int = 100) -> list[FixtureOut]:
    query = select(Fixture).order_by(Fixture.kickoff_at).limit(limit)
    if sport in providers:
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
        if sport_id:
            query = query.where(Fixture.sport_id == sport_id)
    if status:
        query = query.where(Fixture.status == status)
    return [_fixture_out(db, fixture) for fixture in db.scalars(query)]


@app.get("/api/fixtures", response_model=list[FixtureOut])
def fixtures(sport: str | None = Query(default=None), status: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport=sport, status=status, limit=limit)


@app.get("/api/fixtures/today", response_model=list[FixtureOut])
def fixtures_today(sport: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    today = datetime.now(timezone.utc).date()
    return [item for item in _fixtures(db, sport=sport, limit=limit) if item.kickoff_at and item.kickoff_at.date() == today]


@app.get("/api/fixtures/live", response_model=list[FixtureOut])
def fixtures_live(sport: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport=sport, status="live", limit=limit)


@app.get("/api/games/basketball", response_model=list[FixtureOut])
def basketball_games(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport="basketball", limit=limit)


@app.get("/api/games/basketball/live", response_model=list[FixtureOut])
def basketball_live(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[FixtureOut]:
    return _fixtures(db, sport="basketball", status="live", limit=limit)


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
        response = payload.get("response", [])
        data = response[0].get(kind) if response and isinstance(response[0], dict) else response
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=data is not None, data=data, stale=False, message=None if data is not None else "Not available from current provider")
    except ProviderError as exc:
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
def provider_status() -> list[ProviderStatus]:
    return [ProviderStatus(provider=p.name, configured=p.configured, healthy=p.last_success_at is not None and p.last_error is None, last_success_at=p.last_success_at, last_error=p.last_error, latency_ms=p.last_latency_ms, calls_today=p.calls_today) for p in providers.values()]


@app.get("/api/provider-usage", response_model=list[ProviderUsageOut])
def provider_usage() -> list[ProviderUsageOut]:
    return [ProviderUsageOut(provider=p.name, calls_today=p.calls_today, mode=settings.quota_mode) for p in providers.values()]


@app.post("/api/ingestion/today")
async def ingest_today(sport: str = Query(..., pattern="^(football|basketball)$"), db: Session = Depends(get_db)) -> dict:
    provider = providers[sport]
    date = datetime.now(timezone.utc).date().isoformat()
    try:
        items = await provider.fixtures_by_date(date)
    except ProviderError as exc:
        raise HTTPException(503, {"code": "provider_error", "provider": exc.provider, "message": str(exc)}) from exc
    return {"sport": sport, "date": date, "upserted": ingest_fixtures(db, items), "provider": provider.name}


@app.post("/api/ingestion/live")
async def ingest_live(sport: str = Query(..., pattern="^(football|basketball)$"), db: Session = Depends(get_db)) -> dict:
    provider = providers[sport]
    try:
        items = await provider.live_fixtures()
    except ProviderError as exc:
        raise HTTPException(503, {"code": "provider_error", "provider": exc.provider, "message": str(exc)}) from exc
    return {"sport": sport, "upserted": ingest_fixtures(db, items), "provider": provider.name}

