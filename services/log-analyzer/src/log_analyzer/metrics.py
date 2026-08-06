from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["route", "method", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["route", "method"],
)

RUNS_TOTAL = Counter(
    "runs_total",
    "Total simulated runs by terminal status",
    ["status"],
)

RUN_DURATION_SECONDS = Histogram(
    "run_duration_seconds",
    "Simulated run duration in seconds",
    buckets=(0.5, 1, 2, 4, 8, 16, 32, 64),
)

RUNS_IN_PROGRESS = Gauge(
    "runs_in_progress",
    "Number of runs currently executing",
)

RUNS_QUEUE_DEPTH = Gauge(
    "runs_queue_depth",
    "Number of runs waiting for a free execution slot",
)


def latest_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
