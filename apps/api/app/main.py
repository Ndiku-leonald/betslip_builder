import logging
from contextlib import asynccontextmanager
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cache import CacheBackend
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.freshness import data_age_seconds
from app.models import BacktestRun, Competition, Fixture, ModelVersion, OddsSnapshot, Prediction, ProviderConflict, ProviderHealth, ProviderObservation, ProviderUsage, Sport, Team
from app.providers.api_sports import ApiSportsProvider, ProviderError, _parse_dt
from app.providers.easy_soccer_data import EasySoccerDataProvider
from app.providers.livescore_football import LiveScoreFootballProvider
from app.providers.matching import match_fixture
from app.odds.providers import ApiSportsOddsProvider, TheOddsApiProvider, parse_the_odds_api
from app.markets.consensus import ProviderConsensusService
from app.markets.storage import latest_market_snapshots, market_snapshot_history, persist_market_snapshots, persist_provider_observation, latest_provider_observations
from app.markets.value import MarketValueService, odds_consensus
from app.markets.compatibility import model_probability
from app.odds.ontology import NormalizedMarket
from app.providers.reliability import source_reliability, SOURCE_ROLES
from app.quota import QuotaManager
from app.quota_store import PersistentQuotaStore
from app.schemas import DetailOut, FixtureOut, ModelVersionOut, PredictionOut, ProviderStatus, ProviderUsageOut
from app.prediction.service import PredictionService, PredictionUnavailable
from app.services.ingestion import ingest_fixtures

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
settings = get_settings()
cache = CacheBackend(settings.redis_url)
quota_store = PersistentQuotaStore(SessionLocal)
quota = QuotaManager(settings.quota_mode, daily_limits=settings.provider_daily_limits, count_callback=quota_store.count_today, reserve_callback=quota_store.reserve, complete_callback=quota_store.complete)
football = ApiSportsProvider(name="api-football", key=settings.api_football_key, base_url="https://v3.football.api-sports.io", cache=cache, quota=quota)
basketball = ApiSportsProvider(name="api-basketball", key=settings.api_basketball_key, base_url="https://v1.basketball.api-sports.io", cache=cache, quota=quota)
providers = {"football": football, "basketball": basketball}
secondary_football = LiveScoreFootballProvider(settings.livescore_football_base_url, cache=cache) if settings.enable_livescore_football else None
experimental_football = EasySoccerDataProvider(settings.enable_easy_soccer_data)
odds_provider = TheOddsApiProvider(settings.the_odds_api_key) if settings.enable_odds_api else None
api_sports_odds = {"football": ApiSportsOddsProvider(football), "basketball": ApiSportsOddsProvider(basketball)}
consensus_service = ProviderConsensusService()
market_value_service = MarketValueService()
scheduler: AsyncIOScheduler | None = None
app_timezone = ZoneInfo(settings.app_timezone)
prediction_service = PredictionService()


def _app_today() -> date:
    return datetime.now(app_timezone).date()


def _today_bounds_utc() -> tuple[datetime, datetime]:
    today = _app_today()
    start_local = datetime.combine(today, time.min, tzinfo=app_timezone)
    end_local = datetime.combine(today + timedelta(days=1), time.min, tzinfo=app_timezone)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _utc_day_start() -> datetime:
    return datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)


def _record_usage(provider: ApiSportsProvider, endpoint: str, *, status_code: int | None, error: str | None = None) -> None:
    with SessionLocal() as db:
        events = list(provider.last_request_events)
        provider.last_request_events.clear()
        if not events:
            events = [{"endpoint": endpoint, "status_code": status_code if status_code is not None else provider.last_status_code, "latency_ms": provider.last_latency_ms, "rate_limit_remaining": provider.last_rate_limit_remaining, "error": error, "cache_hit": provider.last_cache_hit, "external_request": not provider.last_quota_blocked and not provider.last_cache_hit and provider.configured}]
        health = db.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider.name))
        if health is None:
            health = ProviderHealth(provider=provider.name, configured=provider.configured, healthy=False)
            db.add(health)
        for event in events:
            recorded_at = event.get("requested_at") or datetime.now(timezone.utc)
            effective_status = event["status_code"]
            event_error = event["error"]
            usage = db.get(ProviderUsage, event.get("usage_id")) if event.get("usage_id") else None
            if usage is None:
                usage = ProviderUsage(id=event["usage_id"], provider=provider.name, endpoint=event["endpoint"], requested_at=recorded_at, status_code=effective_status, latency_ms=event["latency_ms"], cache_hit=event["cache_hit"], external_request=event["external_request"], rate_limit_remaining=event["rate_limit_remaining"], error=event_error) if event.get("usage_id") else ProviderUsage(provider=provider.name, endpoint=event["endpoint"], requested_at=recorded_at, status_code=effective_status, latency_ms=event["latency_ms"], cache_hit=event["cache_hit"], external_request=event["external_request"], rate_limit_remaining=event["rate_limit_remaining"], error=event_error)
                db.add(usage)
            else:
                usage.requested_at = recorded_at
                usage.status_code = effective_status
                usage.latency_ms = event["latency_ms"]
                usage.cache_hit = event["cache_hit"]
                usage.external_request = event["external_request"]
                usage.rate_limit_remaining = event["rate_limit_remaining"]
                usage.error = event_error
            health.configured = provider.configured
            if not event["cache_hit"]:
                health.last_latency_ms = event["latency_ms"]
                if event_error or effective_status is None or effective_status >= 400:
                    health.healthy = False
                    health.last_error = event_error or provider.last_error or f"Provider returned HTTP {effective_status}"
                else:
                    health.healthy = True
                    health.last_success_at = recorded_at
                    health.last_error = None
            db.flush()
        health.calls_today = int(db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= _utc_day_start(), ProviderUsage.cache_hit.is_(False), ProviderUsage.external_request.is_(True))) or 0)
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


app = FastAPI(title="SlipIQ API", version="0.1.0", description="Normalized sports data and responsible market intelligence; no bet placement.", lifespan=lifespan)
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
        period=fixture.period, clock=fixture.clock, provider=fixture.provider,
        observed_at=fixture.observed_at, provider_updated_at=fixture.provider_updated_at,
        ingested_at=fixture.ingested_at, freshness=fixture.freshness,
        data_age_seconds=data_age_seconds(fixture.observed_at, fixture.provider_updated_at),
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
    start_utc, end_utc = _today_bounds_utc()
    query = select(Fixture).where(Fixture.kickoff_at >= start_utc, Fixture.kickoff_at < end_utc)
    if sport in providers:
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
        if sport_id:
            query = query.where(Fixture.sport_id == sport_id)
    query = query.order_by(Fixture.kickoff_at).limit(limit)
    return [_fixture_out(db, fixture) for fixture in db.scalars(query)]


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


async def _detail(fixture_id: str, kind: str, db: Session, response_key: str | None = None) -> DetailOut:
    item = db.get(Fixture, fixture_id)
    if not item:
        raise HTTPException(404, "Fixture not found")
    sport_slug = db.scalar(select(Sport.slug).where(Sport.id == item.sport_id))
    provider = providers.get(sport_slug)
    if not provider:
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="unsupported", message="Not available from current provider")
    if not provider.capabilities.get(kind, False):
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="unsupported", message="Not available from current provider")
    if not provider.configured:
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="temporarily_unavailable", message="Provider not configured")
    try:
        payload = await provider.detail(kind, item.provider_fixture_id)
        _record_usage(provider, f"details/{item.provider_fixture_id}", status_code=200)
        response = payload.get("response", [])
        if not response:
            return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="not_covered", data=None, stale=False, message="Not available from current provider")
        if sport_slug == "basketball":
            data = response
        else:
            data = response[0].get(response_key or kind) if isinstance(response[0], dict) else response
        if data is None:
            return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="not_covered", data=None, stale=False, message="Not available from current provider")
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=True, availability="available", data=data, stale=False, message=None)
    except ProviderError as exc:
        _record_usage(provider, f"details/{item.provider_fixture_id}", status_code=exc.status_code, error=str(exc))
        return DetailOut(fixture_id=fixture_id, provider=item.provider, available=False, availability="provider_failure", stale=True, message=str(exc))


@app.get("/api/fixtures/{fixture_id}/stats", response_model=DetailOut)
async def fixture_stats(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "stats", db, response_key="statistics")


@app.get("/api/fixtures/{fixture_id}/events", response_model=DetailOut)
async def fixture_events(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "events", db)


@app.get("/api/fixtures/{fixture_id}/lineups", response_model=DetailOut)
async def fixture_lineups(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "lineups", db)


@app.get("/api/fixtures/{fixture_id}/player-stats", response_model=DetailOut)
async def fixture_player_stats(fixture_id: str, db: Session = Depends(get_db)) -> DetailOut:
    return await _detail(fixture_id, "player_stats", db, response_key="players")


def _prediction_response(db: Session, fixture_id: str, model_version_id: str | None = None) -> dict:
    try:
        return prediction_service.generate(db, fixture_id, model_version_id)
    except PredictionUnavailable as exc:
        return {"available": False, "fixture_id": fixture_id, "reason": str(exc), "markets": {}, "data_quality": {}, "warnings": []}


@app.get("/api/fixtures/{fixture_id}/prediction", response_model=PredictionOut)
def fixture_prediction(fixture_id: str, model_version_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return _prediction_response(db, fixture_id, model_version_id)


@app.post("/api/predictions/generate/{fixture_id}", response_model=PredictionOut)
def generate_prediction(fixture_id: str, model_version_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    return _prediction_response(db, fixture_id, model_version_id)


@app.get("/api/predictions/{prediction_id}", response_model=PredictionOut)
def stored_prediction(prediction_id: str, db: Session = Depends(get_db)) -> dict:
    item = db.get(Prediction, prediction_id)
    if item is None: raise HTTPException(404, "Prediction not found")
    return item.payload


@app.get("/api/models", response_model=list[ModelVersionOut])
def models(sport: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[ModelVersion]:
    return prediction_service.list_models(db, sport)


@app.get("/api/models/{model_id}", response_model=ModelVersionOut)
def model(model_id: str, db: Session = Depends(get_db)) -> ModelVersion:
    item = db.get(ModelVersion, model_id)
    if item is None: raise HTTPException(404, "Model not found")
    return item


@app.get("/api/backtests")
def backtests(db: Session = Depends(get_db)) -> list[dict]:
    return [{"id": item.id, "sport": item.sport, "model_version_id": item.model_version_id, "sample_count": item.sample_count, "metrics": item.metrics, "start_at": item.start_at, "end_at": item.end_at} for item in db.scalars(select(BacktestRun).order_by(BacktestRun.created_at.desc()))]


def _market_out(item: OddsSnapshot) -> dict:
    return {"id": item.id, "fixture_id": item.fixture_id, "provider": item.provider, "bookmaker": item.bookmaker, "source_event_id": item.source_event_id, "market_family": item.market_family, "market_type": item.market_type, "period": item.period, "participant": item.participant, "selection": item.selection, "line": item.line, "decimal_odds": item.decimal_odds, "status": item.market_status, "settlement_semantics": item.settlement_semantics, "observed_at": item.observed_at, "provider_updated_at": item.provider_updated_at}


def _market_key(market: OddsSnapshot) -> str | None:
    line = str(market.line).replace(".", "_") if market.line is not None else None
    if market.market_family == "1x2": return {"home": "home_win", "draw": "draw", "away": "away_win"}.get(market.selection)
    if market.market_family == "moneyline": return f"{market.selection}_moneyline"
    if market.market_family == "btts": return f"btts_{market.selection}"
    if market.market_family in {"totals", "game_total"}: return f"{market.selection}_{line}"
    if market.market_family == "spread": return f"{market.participant}_spread_{market.line:+g}" if market.participant in {"home", "away"} else None
    if market.market_family == "handicap": return f"{market.participant}_handicap_{market.line:+g}" if market.participant in {"home", "away"} else None
    if market.market_family == "team_total": return f"{market.participant}_{market.selection}_{line}"
    return None


def _family_for_market(market: OddsSnapshot) -> str:
    return {"1x2": "1X2", "moneyline": "moneyline", "btts": "btts", "totals": "totals", "game_total": "totals", "team_total": "totals", "handicap": "handicap", "spread": "spread"}.get(market.market_family or "", market.market_family or "unknown")


def _model_market_reliability(db: Session, market: OddsSnapshot, prediction: Prediction | None) -> tuple[float | None, dict]:
    version = db.get(ModelVersion, prediction.model_version_id) if prediction and prediction.model_version_id else None
    if version is None: return None, {"status": "unknown", "reason": "no Stage Two model evidence"}
    family = _family_for_market(market); metrics = version.metrics or {}; family_metrics = (metrics.get("market_families", {}) or {}).get(family)
    key = _market_key(market); market_metrics = (metrics.get("markets", {}) or {}).get(key)
    evidence = market_metrics or family_metrics
    if not evidence: return None, {"status": "unknown", "reason": "no backtest evidence for this market family"}
    sample_count = int(evidence.get("sample_count", 0)); brier = evidence.get("calibrated_brier"); logloss = evidence.get("calibrated_log_loss"); ece = evidence.get("calibrated_ece")
    if not sample_count or brier is None or logloss is None or ece is None: return None, {"status": "low", "sample_count": sample_count, "reason": "incomplete backtest evidence"}
    score = round(100 * (.35 * max(0, 1 - float(ece)) + .3 * max(0, 1 - float(brier)) + .2 * max(0, 1 - min(1, float(logloss) / 2)) + .15 * min(1, sample_count / 100)), 2)
    return score, {"status": "measured", "family": family, "sample_count": sample_count, "calibrated_ece": ece, "calibrated_brier": brier, "calibrated_log_loss": logloss, "coverage": sample_count}


def _model_probability_for_snapshot(db: Session, market: OddsSnapshot, prediction: Prediction | None) -> dict:
    if prediction is None: return {"status": "INSUFFICIENT_MODEL", "reason": "no prediction is available"}
    payload = prediction.payload or {}; calibrated = payload.get("calibrated_probability", payload.get("markets", {})) or {}; raw_values = payload.get("raw_probability", {}) or {}; key = _market_key(market)
    if market.settlement_semantics == "regulation" and prediction.sport == "basketball": return {"status": "INCOMPATIBLE_SETTLEMENT", "reason": "basketball model represents game outcome, not regulation-only outcome"}
    if key in calibrated and isinstance(calibrated[key], (int, float, dict)):
        value = calibrated[key]; raw_value = raw_values.get(key, value)
        if isinstance(value, dict):
            win = float(value.get("win", value.get("probability", 0))); push = float(value.get("push", 0)); loss = float(value.get("lose", max(0, 1 - win - push)))
        else: win, push, loss = float(value), 0.0, 1 - float(value)
        status = (payload.get("calibration_status_by_market", {}) or {}).get(key, "insufficient_calibration")
        status = "fitted" if status == "fitted" else "insufficient_calibration"
        raw_win = float(raw_value.get("win", raw_value.get("probability", 0))) if isinstance(raw_value, dict) else float(raw_value)
        return {"status": "SUPPORTED", "model_probability_structure": {"win_probability": win, "push_probability": push, "loss_probability": loss, "calibration_status": status}, "raw_model_probability": raw_win, "calibrated_model_probability": win if status == "fitted" else None, "calibration_status": status, "reason": None}
    version = db.get(ModelVersion, prediction.model_version_id) if prediction.model_version_id else None
    fixture = db.get(Fixture, market.fixture_id)
    if version is None or fixture is None: return {"status": "INSUFFICIENT_MODEL", "reason": "missing model version or fixture"}
    sport = version.sport or payload.get("sport")
    engine = __import__("app.features.basketball" if sport == "basketball" else "app.features.football", fromlist=["BasketballFeatureEngine" if sport == "basketball" else "FootballFeatureEngine"])
    feature_engine = engine.BasketballFeatureEngine() if sport == "basketball" else engine.FootballFeatureEngine()
    row = next((item for item in feature_engine.build(db, include_unfinished=True) if item.fixture_id == fixture.id), None)
    if row is None: return {"status": "INSUFFICIENT_MODEL", "reason": "fixture has insufficient feature history"}
    model = prediction_service._model(version)
    from app.odds.ontology import normalize_external_market
    normalized = normalize_external_market(fixture_id=market.fixture_id, sport=sport, provider=market.provider, bookmaker=market.bookmaker or "", market_name=market.market_type or market.market_family, selection_name=market.selection, odds=2.0 if market.decimal_odds is None else market.decimal_odds, line=market.line, participant=market.participant, status="open", settlement_semantics=market.settlement_semantics)
    compatibility = model_probability(model, row, normalized)
    if compatibility.get("status") != "SUPPORTED": return {"status": compatibility.get("status", "UNSUPPORTED"), "reason": compatibility.get("reason", "market not mapped")}
    return {"status": "SUPPORTED", "model_probability_structure": {"win_probability": compatibility["win_probability"], "push_probability": compatibility["push_probability"], "loss_probability": compatibility["loss_probability"], "calibration_status": "raw_dynamic_line"}, "raw_model_probability": compatibility["win_probability"], "calibrated_model_probability": None, "calibration_status": "raw_dynamic_line", "reason": None}


def _stored_consensus(db: Session, fixture_id: str) -> dict:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None: return {"agreement": 0.0, "material_conflict": False, "source_count": 0, "conflicts": [], "fields": {}}
    primary = _fixture_out(db, fixture)
    observations = [{"provider": fixture.provider, "home_name": primary.home, "away_name": primary.away, "kickoff_at": primary.kickoff_at, "status": primary.status, "home_score": primary.home_score, "away_score": primary.away_score, "period": primary.period, "clock": primary.clock}]
    observations.extend(latest_provider_observations(db, fixture_id))
    return consensus_service.resolve(observations, primary_source=fixture.provider, fixture_id=fixture_id, db=None)


@app.get("/api/markets")
def markets(sport: str | None = Query(default=None), bookmaker: str | None = Query(default=None), market_family: str | None = Query(default=None), limit: int = Query(default=200, ge=1, le=1000), db: Session = Depends(get_db)) -> list[dict]:
    query = select(OddsSnapshot).order_by(OddsSnapshot.observed_at.desc())
    if sport:
        sport_id = db.scalar(select(Sport.id).where(Sport.slug == sport))
        if sport_id: query = query.join(Fixture, OddsSnapshot.fixture_id == Fixture.id).where(Fixture.sport_id == sport_id)
    if bookmaker: query = query.where(OddsSnapshot.bookmaker == bookmaker)
    if market_family: query = query.where(OddsSnapshot.market_family == market_family)
    result = []; seen = set()
    for item in db.scalars(query):
        identity = (item.provider, item.bookmaker, item.fixture_id, item.market_family, item.market_type, item.period, item.participant, item.selection, item.line, item.settlement_semantics)
        if identity in seen: continue
        seen.add(identity); result.append(_market_out(item))
        if len(result) >= limit: break
    return result


@app.get("/api/fixtures/{fixture_id}/markets")
def fixture_markets(fixture_id: str, db: Session = Depends(get_db)) -> list[dict]:
    return [_market_out(item) for item in latest_market_snapshots(db, fixture_id)]


@app.get("/api/fixtures/{fixture_id}/market-values")
def fixture_market_values(fixture_id: str, profile: str = Query(default="balanced"), db: Session = Depends(get_db)) -> dict:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None: raise HTTPException(404, "Fixture not found")
    prediction = db.scalar(select(Prediction).where(Prediction.fixture_id == fixture_id).order_by(Prediction.generated_at.desc()))
    snapshots = latest_market_snapshots(db, fixture_id); values = []; normalized_snapshots = []
    grouped_snapshots = {}
    for item in snapshots:
        group_key = (item.bookmaker, item.market_family, item.market_type, item.period, item.line, item.participant)
        grouped_snapshots.setdefault(group_key, []).append(item)
    for snapshot in snapshots:
        model_info = _model_probability_for_snapshot(db, snapshot, prediction)
        normalized = NormalizedMarket(fixture_id=snapshot.fixture_id, sport=(prediction.sport if prediction else "football"), bookmaker=snapshot.bookmaker or "", provider=snapshot.provider, market_family=snapshot.market_family or "unknown", market_type=snapshot.market_type or "unknown", period=snapshot.period or "full_game", participant=snapshot.participant or "none", selection=snapshot.selection or "unknown", line=snapshot.line, decimal_odds=snapshot.decimal_odds, status=snapshot.market_status, settlement_semantics=snapshot.settlement_semantics or "full_game", observed_at=snapshot.observed_at or snapshot.created_at, provider_updated_at=snapshot.provider_updated_at, source_event_id=snapshot.source_event_id, raw=snapshot.payload)
        normalized_snapshots.append(normalized)
        group_key = (snapshot.bookmaker, snapshot.market_family, snapshot.market_type, snapshot.period, snapshot.line, snapshot.participant)
        group = [NormalizedMarket(fixture_id=item.fixture_id, sport=normalized.sport, bookmaker=item.bookmaker or "", provider=item.provider, market_family=item.market_family or "unknown", market_type=item.market_type or "unknown", period=item.period or "full_game", participant=item.participant or "none", selection=item.selection or "unknown", line=item.line, decimal_odds=item.decimal_odds, status=item.market_status, settlement_semantics=item.settlement_semantics or "full_game", observed_at=item.observed_at or item.created_at, provider_updated_at=item.provider_updated_at, source_event_id=item.source_event_id, raw=item.payload) for item in grouped_snapshots[group_key]]
        reliability, reliability_components = _model_market_reliability(db, snapshot, prediction)
        agreement_data = _stored_consensus(db, fixture_id)
        source = source_reliability(snapshot.provider, observed_agreement_rate=agreement_data["agreement"] if agreement_data["source_count"] > 1 else None)
        value = market_value_service.evaluate(normalized, model_probability_structure=model_info.get("model_probability_structure"), market_group=group, model_version=prediction.model_version_id if prediction else None, confidence=(prediction.payload or {}).get("model_confidence_score", 0) if prediction else 0, data_quality=(prediction.payload or {}).get("data_quality", {}).get("overall", 0) if prediction else 0, market_reliability=reliability, market_reliability_components=reliability_components, source_reliability=source["reliability_score"], source_reliability_components=source, provider_agreement=agreement_data["agreement"], material_conflict=agreement_data["material_conflict"], calibration_status=model_info.get("calibration_status", "insufficient_calibration"), ttl_seconds=settings.odds_live_ttl_seconds if fixture.status in {"live", "halftime"} else settings.odds_prematch_ttl_seconds)
        value["compatibility"] = model_info["status"]; value["reason"] = model_info.get("reason"); value["raw_model_probability"] = model_info.get("raw_model_probability"); value["calibrated_model_probability"] = model_info.get("calibrated_model_probability"); values.append(value)
    return {"fixture_id": fixture_id, "profile": profile, "values": values, "opportunities": market_value_service.rank(values, profile, min_provider_agreement=settings.min_provider_agreement), "consensus": _stored_consensus(db, fixture_id), "odds_consensus": odds_consensus(normalized_snapshots)}


@app.get("/api/opportunities")
def opportunities(sport: str | None = Query(default=None), profile: str = Query(default="balanced"), minimum_edge: float | None = Query(default=None), db: Session = Depends(get_db)) -> list[dict]:
    fixture_ids = db.scalars(select(Fixture.id)).all(); values = []
    for fixture_id in fixture_ids:
        result = fixture_market_values(fixture_id, profile, db)
        values.extend(result["opportunities"])
    if minimum_edge is not None: values = [item for item in values if item.get("novig_probability_edge", 0) >= minimum_edge]
    if sport: values = [item for item in values if item.get("sport") == sport]
    return sorted(values, key=lambda item: item.get("ranking_score", 0), reverse=True)


@app.get("/api/odds/movement")
def odds_movement(fixture_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[dict]:
    snapshots = market_snapshot_history(db, fixture_id, 5000); groups = {}
    for item in snapshots:
        key = (item.fixture_id, item.bookmaker, item.market_family, item.participant, item.selection, item.line)
        groups.setdefault(key, []).append(item)
    result = []
    for key, items in groups.items():
        items.sort(key=lambda item: item.observed_at or item.created_at)
        first, current = items[0], items[-1]
        result.append({"fixture_id": key[0], "bookmaker": key[1], "market_family": key[2], "participant": key[3], "selection": key[4], "line": key[5], "first_observed_odds": first.decimal_odds, "current_odds": current.decimal_odds, "snapshots": [{"observed_at": item.observed_at, "provider_updated_at": item.provider_updated_at, "decimal_odds": item.decimal_odds} for item in items]})
    return result


@app.get("/api/provider-consensus/{fixture_id}")
async def provider_consensus(fixture_id: str, db: Session = Depends(get_db)) -> dict:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None: raise HTTPException(404, "Fixture not found")
    primary = _fixture_out(db, fixture)
    primary_observation = {"provider": fixture.provider, "home_name": primary.home, "away_name": primary.away, "kickoff_at": primary.kickoff_at, "status": primary.status, "home_score": primary.home_score, "away_score": primary.away_score, "period": primary.period, "clock": primary.clock}
    secondary_status = {"provider": "livescore-football", "status": "unavailable", "reason": "secondary provider disabled"}
    observations = [primary_observation]
    if secondary_football is not None and primary.sport == "football":
        try:
            league = (primary.competition or "football").lower().replace(" ", "-")
            candidates = await secondary_football.fixtures_by_date(primary.kickoff_at.date().isoformat() if primary.kickoff_at else _app_today().isoformat(), league=league)
            match = next((item for item in candidates if match_fixture({"home": item.home_name, "away": item.away_name, "competition": item.competition_name, "kickoff_at": item.kickoff_at}, [{"home": primary.home, "away": primary.away, "competition": primary.competition, "kickoff_at": primary.kickoff_at}])["status"] == "matched"), None)
            if match is None:
                secondary_status = {"provider": secondary_football.name, "status": "not_matched", "reason": "no unambiguous secondary fixture match"}
            else:
                persist_provider_observation(db, fixture.id, match, canonical_home_team=primary.home, canonical_away_team=primary.away)
                observations.append(match)
                secondary_status = {"provider": secondary_football.name, "status": "available", "source_event_id": match.provider_fixture_id, "observed_at": match.observed_at, "provider_updated_at": match.provider_updated_at}
        except Exception as exc:
            secondary_status = {"provider": secondary_football.name, "status": "unavailable", "reason": str(exc)}
    consensus = consensus_service.resolve(observations, primary_source=fixture.provider, fixture_id=fixture_id, db=db)
    return {"fixture_id": fixture_id, "primary": {"provider": fixture.provider, "status": "available", "home": primary.home, "away": primary.away, "observed_at": primary.observed_at, "provider_updated_at": primary.provider_updated_at}, "secondary": secondary_status, "consensus": consensus, "agreement": consensus["agreement"], "conflicts": consensus["conflicts"], "material_conflict": consensus["material_conflict"], "ranking_suppressed": consensus["material_conflict"] and consensus["agreement"] < settings.min_provider_agreement}


@app.get("/api/conflicts")
def conflicts(fixture_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> list[dict]:
    query = select(ProviderConflict).order_by(ProviderConflict.observed_at.desc())
    if fixture_id: query = query.where(ProviderConflict.fixture_id == fixture_id)
    return [{"id": item.id, "fixture_id": item.fixture_id, "field": item.field, "primary_source": item.primary_source, "secondary_source": item.secondary_source, "primary_value": item.primary_value, "secondary_value": item.secondary_value, "severity": item.severity, "resolution": item.resolution} for item in db.scalars(query)]


@app.post("/api/fixtures/{fixture_id}/odds/refresh")
async def refresh_fixture_odds(fixture_id: str, db: Session = Depends(get_db)) -> dict:
    fixture = db.get(Fixture, fixture_id)
    if fixture is None: raise HTTPException(404, "Fixture not found")
    provider = providers.get(db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id)))
    if provider is None or not provider.configured: raise HTTPException(503, "Odds provider not configured")
    try:
        markets_found = await api_sports_odds[db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id))].markets_for_fixture(fixture.provider_fixture_id, db.scalar(select(Sport.slug).where(Sport.id == fixture.sport_id)))
        for market in markets_found: object.__setattr__(market, "fixture_id", fixture.id)
        _record_usage(provider, "odds", status_code=200)
        return {"fixture_id": fixture.id, "stored": persist_market_snapshots(db, markets_found), "provider": provider.name}
    except ProviderError as exc:
        _record_usage(provider, "odds", status_code=exc.status_code, error=str(exc)); raise HTTPException(503, str(exc)) from exc


@app.post("/api/odds/refresh")
async def refresh_odds(sport_key: str = Query(..., min_length=2, max_length=80), fixture_id: str | None = Query(default=None), db: Session = Depends(get_db)) -> dict:
    if odds_provider is None or not odds_provider.configured:
        raise HTTPException(503, "The Odds API is not configured")
    if fixture_id:
        fixture = db.get(Fixture, fixture_id)
        if fixture is None: raise HTTPException(404, "Fixture not found")
        fixture_out = _fixture_out(db, fixture)
        sport_slug = fixture_out.sport
        try:
            events = await odds_provider.list_events(sport_key)
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        known = {"home": fixture_out.home, "away": fixture_out.away, "competition": fixture_out.competition, "kickoff_at": fixture_out.kickoff_at}
        matched = next((event for event in events if match_fixture({"home": event.get("home_team"), "away": event.get("away_team"), "competition": sport_key, "kickoff_at": _parse_dt(event.get("commence_time"))}, [known])["status"] == "matched"), None)
        if matched is None:
            raise HTTPException(409, "No unambiguous odds event matched the canonical fixture")
        markets_found = parse_the_odds_api([matched], fixture.id, sport_slug, odds_provider.name)
        stored = persist_market_snapshots(db, markets_found)
        return {"provider": odds_provider.name, "stored": stored, "fixture_id": fixture.id, "source_event_id": matched.get("id")}
    try:
        events = await odds_provider.list_events(sport_key)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    markets_found = []
    for event in events:
        markets_found.extend(parse_the_odds_api([event], event.get("id", ""), "basketball" if "basketball" in sport_key else "football", odds_provider.name))
    # External event IDs are not canonical fixture IDs; storage requires a
    # resolved internal fixture.  Return discovery data until matching runs.
    return {"provider": odds_provider.name, "events": len(events), "markets": len(markets_found), "stored": 0, "reason": "pass an internal fixture_id after canonical event matching"}


@app.get("/api/providers/status", response_model=list[ProviderStatus])
def provider_status(db: Session = Depends(get_db)) -> list[ProviderStatus]:
    result = []
    for provider in providers.values():
        health = db.scalar(select(ProviderHealth).where(ProviderHealth.provider == provider.name))
        if health is not None:
            result.append(ProviderStatus(provider=provider.name, configured=provider.configured, healthy=provider.configured and health.healthy, last_success_at=health.last_success_at, last_error=health.last_error, latency_ms=health.last_latency_ms, calls_today=health.calls_today, capabilities=provider.capabilities))
            continue
        day_start = _utc_day_start()
        usage = list(db.scalars(select(ProviderUsage).where(ProviderUsage.provider == provider.name).order_by(ProviderUsage.requested_at.desc()).limit(100)))
        successful = next((item for item in usage if item.status_code is not None and item.status_code < 400 and not item.error), None)
        latest = usage[0] if usage else None
        calls_today = db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= day_start, ProviderUsage.cache_hit.is_(False), ProviderUsage.external_request.is_(True))) or 0
        result.append(ProviderStatus(provider=provider.name, configured=provider.configured, healthy=bool(successful and (latest is None or not latest.error)), last_success_at=successful.requested_at if successful else provider.last_success_at, last_error=latest.error if latest and latest.error else provider.last_error, latency_ms=latest.latency_ms if latest else provider.last_latency_ms, calls_today=int(calls_today), capabilities=provider.capabilities))
    return result


@app.get("/api/data-sources")
def data_sources() -> list[dict]:
    return [
        {"provider": "api-football", "configured": football.configured, "enabled": True, "role": "primary", "capabilities": football.capabilities},
        {"provider": "api-basketball", "configured": basketball.configured, "enabled": True, "role": "primary", "capabilities": basketball.capabilities},
        {"provider": "livescore-football", "configured": bool(secondary_football), "enabled": bool(secondary_football), "role": "secondary", "capabilities": (secondary_football.capabilities if secondary_football else {})},
        {"provider": "easy-soccer-data", "configured": experimental_football.configured, "enabled": experimental_football.enabled, "role": "experimental_secondary", "capabilities": experimental_football.capabilities},
        {"provider": "the-odds-api", "configured": bool(odds_provider and odds_provider.configured), "enabled": bool(odds_provider), "role": "odds_context", "capabilities": {"odds": True}},
        {"provider": "betpawa-import", "configured": False, "enabled": True, "role": "target_import", "capabilities": {"json_import": True, "csv_import": True, "manual_import": True}},
    ]


@app.get("/api/providers/reliability")
def provider_reliability() -> list[dict]:
    return [source_reliability(provider) for provider in SOURCE_ROLES]


@app.get("/api/provider-usage", response_model=list[ProviderUsageOut])
def provider_usage(db: Session = Depends(get_db)) -> list[ProviderUsageOut]:
    today_start = _utc_day_start()
    result = []
    for provider in providers.values():
        count = db.scalar(select(func.count(ProviderUsage.id)).where(ProviderUsage.provider == provider.name, ProviderUsage.requested_at >= today_start, ProviderUsage.cache_hit.is_(False), ProviderUsage.external_request.is_(True))) or 0
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
