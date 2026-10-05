import argparse
import asyncio
from datetime import datetime, timezone

from app.db import SessionLocal
from app.main import provider_for_sport
from app.providers.api_sports import ProviderError
from app.providers.football_data import FootballDataError
from app.services.ingestion import ingest_fixtures


async def run(sport: str, date: str | None, live: bool) -> None:
    provider = provider_for_sport(sport)
    if live and sport == "football" and provider.name == "football-data.org":
        raise RuntimeError("Live football ingestion is disabled for football-data.org")
    if live:
        items = await provider.live_fixtures()
    elif sport == "football" and provider.name == "football-data.org":
        items = await provider.fixtures_by_date(date or datetime.now(timezone.utc).date().isoformat(), league="PL")
    else:
        items = await provider.fixtures_by_date(date or datetime.now(timezone.utc).date().isoformat())
    with SessionLocal() as db:
        print({"sport": sport, "upserted": ingest_fixtures(db, items)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sport", choices=["football", "basketball"], required=True)
    parser.add_argument("--date")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.sport, args.date, args.live))
    except ProviderError as exc:
        raise SystemExit(str(exc)) from exc
    except FootballDataError as exc:
        raise SystemExit(exc.reason_code or "provider_error") from exc
