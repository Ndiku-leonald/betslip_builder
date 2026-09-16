"""Isolated experimental EasySoccerData adapter.

The MIT wrapper license does not change the terms of the underlying providers.
This adapter is disabled by default and is never required by core ingestion.
"""
from __future__ import annotations


class EasySoccerDataProvider:
    name = "easy-soccer-data"
    capabilities = {"live": True, "statistics": True, "events": True}

    def __init__(self, enabled: bool = False, client=None):
        self.enabled = bool(enabled); self.client = client; self.configured = self.enabled and client is not None

    def _disabled(self):
        raise RuntimeError("EasySoccerData is disabled or has no explicitly supplied client")

    async def live_fixtures(self):
        if not self.configured: self._disabled()
        return await self.client.get_events(live=True)
