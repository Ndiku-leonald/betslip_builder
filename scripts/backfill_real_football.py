"""Quota-bounded API-Football league-season backfill."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.db import SessionLocal  # noqa: E402
from app.historical.ingest import ingest_league_season  # noqa: E402
from app.main import football  # noqa: E402
from app.providers.api_sports import ProviderError  # noqa: E402


async def run(leagues: list[str], season: str, max_requests: int, dry_run: bool) -> dict:
    if max_requests <= 0:
        raise ValueError("max_requests must be positive")
    if len(leagues) > max_requests:
        raise ValueError("the explicit league list is larger than max_requests")
    result = {"season": season, "requested_leagues": leagues, "dry_run": dry_run, "results": [], "external_requests": 0}
    if dry_run:
        return result
    with SessionLocal() as db:
        for league in leagues:
            football.request_budget = max_requests - result["external_requests"]
            try:
                item = await ingest_league_season(db, football, league, season)
                result["results"].append(item)
            except ProviderError as exc:
                result["results"].append({"league": str(league), "season": season, "error": str(exc), "status_code": exc.status_code})
            result["external_requests"] += sum(event.get("external_request", False) for event in football.last_request_events)
            if result["external_requests"] >= max_requests:
                break
    football.request_budget = None
    result["fixtures"] = sum(int(item.get("fixtures", 0)) for item in result["results"])
    result["finished"] = sum(int(item.get("finished", 0)) for item in result["results"])
    result["statistics"] = 0
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill explicitly selected API-Football league seasons")
    parser.add_argument("--league", action="append", required=True, help="API-Football league ID; repeat for each allowlisted league")
    parser.add_argument("--season", required=True, help="Historical season, for example 2024")
    parser.add_argument("--max-requests", type=int, required=True, help="Hard cap on outbound provider requests")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.league, args.season, args.max_requests, args.dry_run)), default=str))
