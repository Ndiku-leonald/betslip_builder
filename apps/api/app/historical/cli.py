import argparse
import asyncio
from datetime import date, timedelta

from app.config import get_settings
from app.db import SessionLocal
from app.historical.ingest import ingest_range
from app.providers.api_sports import ApiSportsProvider
from app.cache import CacheBackend
from app.main import basketball, football


def main(sport: str) -> None:
    parser = argparse.ArgumentParser(description=f"Quota-aware {sport} historical backfill")
    parser.add_argument("--league", required=False); parser.add_argument("--season", required=False)
    parser.add_argument("--start-date", type=date.fromisoformat); parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--max-requests", type=int); parser.add_argument("--dry-run", action="store_true"); parser.add_argument("--no-stats", action="store_true"); parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()
    start = args.start_date or date.today() - timedelta(days=30); end = args.end_date or date.today()
    if end < start: parser.error("end date must not precede start date")
    provider = football if sport == "football" else basketball
    with SessionLocal() as db: result = asyncio.run(ingest_range(db, provider, start, end, league=args.league, season=args.season, max_requests=args.max_requests, dry_run=args.dry_run, resume=not args.no_resume, include_stats=not args.no_stats))
    print(result)
