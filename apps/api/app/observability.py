import json
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.security import redact_secrets


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "slipiq-api",
            "logger": record.name,
            "message": redact_secrets(record.getMessage()),
        }
        for key in ("request_id", "route", "method", "status_code", "provider", "operation", "fixture_id"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = redact_secrets(value)
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    if not root.handlers:
        handler = logging.StreamHandler()
        root.addHandler(handler)
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())


class Metrics:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.latencies: list[float] = []

    def observe_http(self, method: str, route: str, status: int, elapsed_ms: float) -> None:
        self.counters[f"http_requests_total|{method}|{route.split('?', 1)[0]}|{status}"] += 1
        self.latencies = (self.latencies + [elapsed_ms])[-1000:]

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def prometheus(self) -> str:
        lines = ["# HELP slipiq_http_requests_total HTTP requests", "# TYPE slipiq_http_requests_total counter"]
        for key, value in sorted(self.counters.items()):
            if key.startswith("http_requests_total|"):
                _, method, route, status = key.split("|", 3)
                lines.append(f'slipiq_http_requests_total{{method="{method}",route="{route}",status="{status}"}} {value}')
            else:
                lines.append(f"slipiq_{key.replace('-', '_').replace('.', '_').replace('|', '_')} {value}")
        return "\n".join(lines) + "\n"
