from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Must be set before `log_analyzer.api` is first imported — Settings.from_env()
# runs once at module import time.
os.environ.setdefault("RUN_MIN_DURATION_SECONDS", "0")
os.environ.setdefault("RUN_MAX_DURATION_SECONDS", "0.02")
os.environ.setdefault("RUN_FAILURE_RATE", "0")
os.environ.setdefault("RUN_MAX_CONCURRENCY", "5")
os.environ.setdefault("CLICKHOUSE_HOST", "unused-in-tests")

import pytest  # noqa: E402


class FakeClickHouseStore:
    """In-memory stand-in for ClickHouseStore — no network/ClickHouse involved."""

    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self._runs: dict[str, dict[str, Any]] = {}

    def ping(self) -> bool:
        return self.healthy

    def ensure_tables(self) -> None:
        pass

    def insert_run(self, run_id: str, input_json: str, started_at: datetime) -> None:
        self._runs[run_id] = {
            "id": run_id,
            "status": "READY",
            "input_json": input_json,
            "started_at": started_at,
            "finished_at": None,
            "duration_seconds": None,
        }

    def update_run_status(
        self,
        run_id: str,
        status: str,
        input_json: str,
        started_at: datetime,
        finished_at: datetime | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        self._runs[run_id] = {
            "id": run_id,
            "status": status,
            "input_json": input_json,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": duration_seconds,
        }

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._runs.get(run_id)


@pytest.fixture
def fake_store():
    return FakeClickHouseStore()


@pytest.fixture
def client(fake_store):
    from fastapi.testclient import TestClient

    from log_analyzer import api as api_module

    api_module._store = fake_store
    with TestClient(api_module.app) as test_client:
        yield test_client
    api_module._store = None
