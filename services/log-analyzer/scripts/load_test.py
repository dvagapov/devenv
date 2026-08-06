#!/usr/bin/env python3
"""Fire concurrent POST /runs requests against the runs API to generate load and trigger failures/alerts."""
from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def start_run(base_url: str) -> str:
    req = urllib.request.Request(f"{base_url}/runs", method="POST", data=b"{}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return f"{resp.status}"
    except urllib.error.HTTPError as exc:
        return f"{exc.code}"
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Runs API load generator")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--requests", type=int, default=200)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--rps", type=float, default=10.0, help="target requests per second")
    args = parser.parse_args()

    delay = 1.0 / args.rps if args.rps > 0 else 0
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = []
        for i in range(args.requests):
            futures.append(pool.submit(start_run, args.base_url))
            if delay:
                time.sleep(delay)

        results = [f.result() for f in futures]

    counts: dict[str, int] = {}
    for r in results:
        counts[r] = counts.get(r, 0) + 1
    print(f"sent {args.requests} requests, results: {counts}")


if __name__ == "__main__":
    main()
