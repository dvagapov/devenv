from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from . import metrics
from .clickhouse_store import ClickHouseStore
from .config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("log_analyzer")

settings = Settings.from_env()
run_semaphore = asyncio.Semaphore(settings.run_max_concurrency)

app = FastAPI(title="Runs API", description="Simulated web-scraping run service")

_store: ClickHouseStore | None = None


def get_store() -> ClickHouseStore:
    """Lazily connect to ClickHouse. Never crashes the process on failure — a
    transient/not-yet-ready ClickHouse should degrade readiness, not kill the pod."""
    global _store
    if _store is None:
        candidate = ClickHouseStore(settings)
        candidate.ensure_tables()
        _store = candidate
    return _store


@app.on_event("startup")
def on_startup() -> None:
    try:
        get_store()
    except Exception:
        logger.exception("ClickHouse not reachable at startup; will retry lazily on first use")


@app.middleware("http")
async def record_http_metrics(request: Request, call_next):
    route = request.url.path
    method = request.method
    if route == "/metrics":
        return await call_next(request)

    # /health(/live) are excluded from the duration histogram — readiness/liveness
    # probes fire every few seconds and would dominate the sample count, skewing
    # latency stats. They ARE still counted in the request counter: that's what the
    # availability/synthetic-check monitor (deploy/charts/grafana-monitoring) reads.
    skip_duration = route in ("/health", "/health/live")

    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        metrics.HTTP_REQUESTS_TOTAL.labels(route=route, method=method, status="500").inc()
        raise
    if not skip_duration:
        duration = time.perf_counter() - start
        metrics.HTTP_REQUEST_DURATION_SECONDS.labels(route=route, method=method).observe(duration)
    metrics.HTTP_REQUESTS_TOTAL.labels(route=route, method=method, status=str(response.status_code)).inc()
    return response


async def _execute_run(run_id: str, input_json: str, started_at: datetime, force_fail: bool = False) -> None:
    metrics.RUNS_QUEUE_DEPTH.inc()
    async with run_semaphore:
        metrics.RUNS_QUEUE_DEPTH.dec()
        metrics.RUNS_IN_PROGRESS.inc()
        get_store().update_run_status(run_id, "RUNNING", input_json, started_at)
        run_start = time.perf_counter()
        try:
            duration = random.uniform(
                settings.run_min_duration_seconds, settings.run_max_duration_seconds
            )
            await asyncio.sleep(duration)
            failed = force_fail or random.random() < settings.run_failure_rate
            status = "FAILED" if failed else "SUCCEEDED"
        finally:
            elapsed = time.perf_counter() - run_start
            metrics.RUN_DURATION_SECONDS.observe(elapsed)
            metrics.RUNS_IN_PROGRESS.dec()

        finished_at = datetime.utcnow().replace(microsecond=0)
        get_store().update_run_status(
            run_id,
            status,
            input_json,
            started_at,
            finished_at=finished_at,
            duration_seconds=elapsed,
        )
        metrics.RUNS_TOTAL.labels(status=status).inc()
        logger.info("run %s finished with status %s in %.2fs", run_id, status, elapsed)


@app.post("/runs", status_code=201)
async def start_run(body: Optional[dict] = None) -> dict:
    body = body or {}
    run_id = uuid.uuid4().hex
    input_payload = body.get("input", {})
    input_json = json.dumps(input_payload)
    started_at = datetime.utcnow().replace(microsecond=0)

    # Test-only overrides for exercising alerts/dashboards on demand — never set by
    # normal clients. See services/log-analyzer/scripts/trigger_alerts.py.
    force_fail = bool(body.get("forceFail", False))
    force_slow_ms = int(body.get("forceSlowMs", 0) or 0)

    get_store().insert_run(run_id, input_json, started_at)
    asyncio.create_task(_execute_run(run_id, input_json, started_at, force_fail=force_fail))

    if force_slow_ms > 0:
        # Delays this response itself (not the background run) so
        # http_request_duration_seconds — what the latency alert/dashboard panel
        # actually measure — visibly spikes.
        await asyncio.sleep(force_slow_ms / 1000)

    return {"id": run_id, "status": "READY", "startedAt": started_at.isoformat() + "Z"}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    run = get_store().get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "id": run["id"],
        "status": run["status"],
        "startedAt": run["started_at"].isoformat() + "Z" if run["started_at"] else None,
        "finishedAt": run["finished_at"].isoformat() + "Z" if run["finished_at"] else None,
        "durationSeconds": run["duration_seconds"],
    }


@app.get("/health/live")
async def health_live() -> JSONResponse:
    """Liveness: process is up and serving requests. No external dependencies —
    a ClickHouse outage must not get this pod killed and restarted."""
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/health")
async def health() -> JSONResponse:
    """Readiness: can this pod actually serve traffic right now."""
    try:
        healthy = get_store().ping()
    except Exception:
        logger.exception("health check failed")
        healthy = False
    if not healthy:
        return JSONResponse(status_code=503, content={"status": "unhealthy"})
    return JSONResponse(status_code=200, content={"status": "ok"})


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    body, content_type = metrics.latest_metrics()
    return Response(content=body, media_type=content_type)
