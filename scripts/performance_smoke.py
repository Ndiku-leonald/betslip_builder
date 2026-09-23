from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
import urllib.request

os.environ.pop("SSLKEYLOGFILE", None)


def request(url: str) -> tuple[bool, float]:
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            ok = response.status < 500
    except Exception:
        ok = False
    return ok, (time.perf_counter() - started) * 1000


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=30)
    args = parser.parse_args()
    urls = [args.base.rstrip("/") + path for path in ("/health", "/api/fixtures?limit=1", "/api/markets?limit=1")] * max(1, args.requests // 3)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(request, urls))
    latencies = [latency for _, latency in results]
    report = {"requests": len(results), "errors": sum(not ok for ok, _ in results), "p50_ms": statistics.median(latencies), "max_ms": max(latencies)}
    print(json.dumps(report, indent=2))
    return 0 if report["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
