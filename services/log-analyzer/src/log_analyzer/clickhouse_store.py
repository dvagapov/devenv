from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import clickhouse_connect

from .config import Settings


class ClickHouseStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
            database=settings.clickhouse_database,
            secure=False,
        )

    def ping(self) -> bool:
        return self.client.ping()

    def ensure_tables(self) -> None:
        self.client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.settings.clickhouse_database}.{self.settings.runs_table} (
                id String,
                status Enum8('READY' = 1, 'RUNNING' = 2, 'SUCCEEDED' = 3, 'FAILED' = 4),
                input_json String,
                started_at DateTime,
                finished_at Nullable(DateTime),
                duration_seconds Nullable(Float64),
                created_at DateTime
            ) ENGINE = ReplacingMergeTree(created_at)
            ORDER BY (id)
            """
        )

    def insert_run(self, run_id: str, input_json: str, started_at: datetime) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        self.client.insert(
            f"{self.settings.clickhouse_database}.{self.settings.runs_table}",
            [[run_id, "READY", input_json, started_at, None, None, now]],
            column_names=[
                "id",
                "status",
                "input_json",
                "started_at",
                "finished_at",
                "duration_seconds",
                "created_at",
            ],
        )

    def update_run_status(
        self,
        run_id: str,
        status: str,
        input_json: str,
        started_at: datetime,
        finished_at: datetime | None = None,
        duration_seconds: float | None = None,
    ) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        self.client.insert(
            f"{self.settings.clickhouse_database}.{self.settings.runs_table}",
            [[run_id, status, input_json, started_at, finished_at, duration_seconds, now]],
            column_names=[
                "id",
                "status",
                "input_json",
                "started_at",
                "finished_at",
                "duration_seconds",
                "created_at",
            ],
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        query = f"""
            SELECT id, status, input_json, started_at, finished_at, duration_seconds
            FROM {self.settings.clickhouse_database}.{self.settings.runs_table}
            FINAL
            WHERE id = %(id)s
            LIMIT 1
        """
        rows = self.client.query(query, parameters={"id": run_id}).named_results()
        rows = list(rows)
        if not rows:
            return None
        return dict(rows[0])

    def count_recent_by_status(self, status: str, minutes: int) -> int:
        query = f"""
            SELECT count() AS value
            FROM {self.settings.clickhouse_database}.{self.settings.runs_table}
            FINAL
            WHERE status = %(status)s
              AND created_at >= now() - INTERVAL %(minutes)s MINUTE
        """
        rows = self.client.query(
            query, parameters={"status": status, "minutes": minutes}
        ).result_rows
        return int(rows[0][0]) if rows else 0
