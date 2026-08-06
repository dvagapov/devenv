#!/usr/bin/env python3
"""Drive the Runs API into each golden-signal alert condition on demand.

Unlike load_test.py (generic load), this targets each golden-signal monitor in
deploy/charts/grafana-monitoring/templates/monitors/ (errors.yaml, latency.yaml,
saturation.yaml) specifically, using the forceFail/forceSlowMs test-only request
overrides so results are deterministic instead of waiting on random
RUN_FAILURE_RATE luck.

Usage:
  python trigger_alerts.py errors       # HighErrorRate + NoSuccessfulRuns
  python trigger_alerts.py latency      # HighLatencyP95
  python trigger_alerts.py saturation   # SaturationHigh
  python trigger_alerts.py all          # all of the above, one after another

Alert eval windows are 5-10m (see the alert rules) — this script keeps
sending requests for the duration of each scenario so the condition holds
across enough consecutive evaluations to actually fire, not just spike once.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def post_run(base_url: str, body: dict) -> str:
    data = json.dumps(body).encode()
    req = urllib.request.Request(f"{base_url}/runs", method="POST", data=data)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return str(resp.status)
    except urllib.error.HTTPError as exc:
        return str(exc.code)
    except Exception as exc:  # noqa: BLE001
        return f"error:{exc}"


def scenario_errors(base_url: str, duration_s: int) -> None:
    """Force every run to fail for the duration. Trips HighErrorRate (>10% failures,
    5m window) and, since nothing succeeds, NoSuccessfulRuns (10m window) too."""
    print(f"[errors] forcing failures for {duration_s}s ...")
    deadline = time.time() + duration_s
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = []
        while time.time() < deadline:
            futures.append(pool.submit(post_run, base_url, {"forceFail": True}))
            time.sleep(0.2)
        results = [f.result() for f in futures]
    print(f"[errors] sent {len(results)} forced-failure requests")


def scenario_latency(base_url: str, duration_s: int, slow_ms: int) -> None:
    """Force each request's own HTTP response to be slow. Trips HighLatencyP95
    (avg http_request_duration_seconds over threshold, 5m window)."""
    print(f"[latency] forcing {slow_ms}ms response delay for {duration_s}s ...")
    deadline = time.time() + duration_s
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = []
        while time.time() < deadline:
            futures.append(pool.submit(post_run, base_url, {"forceSlowMs": slow_ms}))
        results = [f.result() for f in futures]
    print(f"[latency] sent {len(results)} slow requests")


def scenario_saturation(base_url: str, duration_s: int, concurrency: int) -> None:
    """Sustain concurrency well above RUN_MAX_CONCURRENCY (default 5) for the
    duration. Trips SaturationHigh (runs_in_progress/RUN_MAX_CONCURRENCY > 0.8,
    5m window) — needs continuous arrivals since individual runs finish in
    seconds, unlike errors/no-successful-runs where failed rows just sit in
    the rolling window."""
    print(f"[saturation] sustaining concurrency={concurrency} for {duration_s}s ...")
    deadline = time.time() + duration_s
    sent = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = []
        while time.time() < deadline:
            for _ in range(concurrency):
                futures.append(pool.submit(post_run, base_url, {}))
                sent += 1
            time.sleep(0.5)
        for f in futures:
            f.result()
    print(f"[saturation] sent {sent} requests")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trigger each Runs API golden-signal alert")
    parser.add_argument("scenario", choices=["errors", "latency", "saturation", "all"])
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--duration", type=int, default=360, help="seconds to sustain the scenario (default 360 = 6m, covers the 5-10m eval windows)")
    parser.add_argument("--slow-ms", type=int, default=6000, help="response delay for the latency scenario (default 6000ms > 5s threshold)")
    parser.add_argument("--concurrency", type=int, default=25, help="concurrent in-flight requests for the saturation scenario")
    args = parser.parse_args()

    scenarios = [args.scenario] if args.scenario != "all" else ["errors", "latency", "saturation"]
    for name in scenarios:
        if name == "errors":
            scenario_errors(args.base_url, args.duration)
        elif name == "latency":
            scenario_latency(args.base_url, args.duration, args.slow_ms)
        elif name == "saturation":
            scenario_saturation(args.base_url, args.duration, args.concurrency)

    print("Done. Check Grafana → Alerting → Alert rules (folder 'Runs API') for firing state;"
          " alerts evaluate on their own interval (1m) and need `for:` duration to elapse.")


if __name__ == "__main__":
    main()
