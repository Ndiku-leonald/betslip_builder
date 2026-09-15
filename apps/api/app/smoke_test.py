"""Minimal real-provider smoke checks; never prints credentials."""

import argparse
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.main import providers
from app.providers.api_sports import ApiSportsProvider, ProviderError


def report(label: str, state: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"{label}: {state}{suffix}")


async def run_provider(label: str, provider: ApiSportsProvider, detail_kind: str, detail_label: str) -> bool:
    if not provider.configured:
        report(f"{label} today", "SKIPPED", "key not configured")
        report(f"{label} live", "SKIPPED", "key not configured")
        report(f"{label} {detail_label}", "SKIPPED", "key not configured")
        return True

    date = datetime.now(ZoneInfo(get_settings().app_timezone)).date().isoformat()
    candidates = []
    passed = True
    try:
        today = await provider.fixtures_by_date(date)
        candidates.extend(today)
        report(f"{label} today", "PASS", f"{len(today)} records")
    except ProviderError as exc:
        report(f"{label} today", "FAILED", str(exc))
        passed = False
    try:
        live = await provider.live_fixtures()
        candidates.extend(live)
        report(f"{label} live", "PASS", f"{len(live)} records")
    except ProviderError as exc:
        report(f"{label} live", "FAILED", str(exc))
        passed = False
    if not candidates:
        report(f"{label} {detail_label}", "SKIPPED", "no fixture returned to inspect")
        return passed
    item = candidates[0]
    try:
        await provider.detail(detail_kind, item.provider_fixture_id)
        report(f"{label} {detail_label}", "PASS", f"fixture {item.provider_fixture_id}")
    except ProviderError as exc:
        report(f"{label} {detail_label}", "FAILED", str(exc))
        passed = False
    return passed


async def main() -> int:
    football_ok = await run_provider("API-Football", providers["football"], "stats", "fixture detail")
    basketball_ok = await run_provider("API-Basketball", providers["basketball"], "stats", "statistics")
    return 0 if football_ok and basketball_ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run minimal API-Sports checks without printing API keys.")
    parser.parse_args()
    raise SystemExit(asyncio.run(main()))
