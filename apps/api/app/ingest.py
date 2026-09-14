import argparse
import asyncio
from datetime import datetime, timezone

from app.db import SessionLocal
from app.main import providers
from app.providers.api_sports import ProviderError
from app.services.ingestion import ingest_fixtures


async def run(sport: str, date: str | None, live: bool) -> None:
    provider = providers[sport]
    items = await (provider.live_fixtures() if live else provider.fixtures_by_date(date or datetime.now(timezone.utc).date().isoformat()))
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

