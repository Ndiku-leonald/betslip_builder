"""Provider-neutral deployment smoke checks; provider credentials are not required."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

os.environ.pop("SSLKEYLOGFILE", None)


def request_json(base: str, path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict[str, str], str]:
    request = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(payload).encode() if payload is not None else None, headers={"Accept": "application/json", "Content-Type": "application/json"}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers), error.read().decode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--frontend", default="http://localhost:3000")
    args = parser.parse_args()
    checks = []
    for path, expected in (("/health", 200), ("/ready", 200), ("/livez", 200), ("/api/fixtures?limit=1", 200), ("/api/markets?limit=1", 200), ("/api/slips/build", 422)):
        status, headers, body = request_json(args.api, path, "POST", {}) if path == "/api/slips/build" else request_json(args.api, path)
        ok = status == expected and "slipiq" not in body.lower() if path == "/health" else status == expected
        if path == "/health":
            ok = status == expected and "password" not in body.lower() and "api_key" not in body.lower()
        if path.startswith("/api/") and path != "/api/slips/build":
            ok = ok and (headers.get("X-Content-Type-Options") or headers.get("x-content-type-options")) == "nosniff" and bool(headers.get("X-Request-ID") or headers.get("x-request-id"))
        checks.append({"path": path, "status": status, "ok": ok})
    try:
        frontend_status, _, _ = request_json(args.frontend, "/")
        checks.append({"path": "frontend:/", "status": frontend_status, "ok": frontend_status == 200})
    except Exception as exc:
        checks.append({"path": "frontend:/", "status": None, "ok": False, "error": str(exc)})
    print(json.dumps(checks, indent=2))
    return 0 if all(item["ok"] for item in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
