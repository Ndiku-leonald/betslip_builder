"""Dedicated production worker entrypoint.

Only this process role starts the APScheduler jobs in production. API web
processes never start scheduled ingestion.
"""

import asyncio

from app.config import get_settings, validate_production_settings
from app.main import start_scheduler, stop_scheduler


async def run() -> None:
    settings = get_settings()
    validate_production_settings(settings)
    if settings.app_env == "production" and settings.app_process_role != "worker":
        raise RuntimeError("worker entrypoint requires APP_PROCESS_ROLE=worker")
    await start_scheduler()
    try:
        await asyncio.Event().wait()
    finally:
        await stop_scheduler()


if __name__ == "__main__":
    asyncio.run(run())
