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

    def ensure_tables(self) -> None:
        self.client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.settings.clickhouse_database}.analyzer_state (
                job_id String,
                run_id String,
                step String,
                status Enum8('pending' = 1, 'in_progress' = 2, 'completed' = 3, 'failed' = 4),
                checkpoint String,
                started_at DateTime,
                updated_at DateTime
            ) ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY (job_id, run_id, step)
            """
        )
        self.client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.settings.clickhouse_database}.analyzer_reports (
                job_id String,
                run_id String,
                window_start DateTime,
                window_end DateTime,
                status LowCardinality(String),
                summary String,
                prompt String,
                model String,
                anomalies_json String,
                metrics_json String,
                created_at DateTime
            ) ENGINE = ReplacingMergeTree(created_at)
            ORDER BY (job_id, run_id)
            """
        )
        self.client.command(
            f"""
            CREATE TABLE IF NOT EXISTS {self.settings.clickhouse_database}.analyzer_knowledge (
                job_id String,
                run_id String,
                service_name String,
                signal_type LowCardinality(String),
                insight String,
                confidence Float64,
                created_at DateTime
            ) ENGINE = MergeTree()
            ORDER BY (job_id, run_id, service_name, signal_type)
            """
        )

    def detect_service_column(self) -> str:
        if self.settings.service_column.upper() != "AUTO":
            return self.settings.service_column

        table = self.settings.logs_table
        query = """
            SELECT name
            FROM system.columns
            WHERE database = %(database)s AND table = %(table)s
        """
        rows = self.client.query(
            query,
            parameters={
                "database": self.settings.clickhouse_database,
                "table": table,
            },
        ).result_rows
        candidates = {row[0] for row in rows}
        for col in ("ServiceName", "service_name", "container_name", "pod_name"):
            if col in candidates:
                return col
        return "container_name"

    def get_step_checkpoint(self, job_id: str, run_id: str, step: str) -> dict[str, Any] | None:
        query = f"""
            SELECT checkpoint
            FROM {self.settings.clickhouse_database}.analyzer_state
            WHERE job_id = %(job_id)s
              AND run_id = %(run_id)s
              AND step = %(step)s
              AND status = 'completed'
            ORDER BY updated_at DESC
            LIMIT 1
        """
        rows = self.client.query(
            query,
            parameters={"job_id": job_id, "run_id": run_id, "step": step},
        ).result_rows
        if not rows:
            return None
        payload = rows[0][0] or "{}"
        return json.loads(payload)

    def upsert_step(self, job_id: str, run_id: str, step: str, status: str, checkpoint: dict[str, Any]) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        self.client.insert(
            f"{self.settings.clickhouse_database}.analyzer_state",
            [
                [
                    job_id,
                    run_id,
                    step,
                    status,
                    json.dumps(checkpoint, ensure_ascii=True),
                    now,
                    now,
                ]
            ],
            column_names=[
                "job_id",
                "run_id",
                "step",
                "status",
                "checkpoint",
                "started_at",
                "updated_at",
            ],
        )

    def query_log_counts(
        self, service_col: str, window_start: datetime, window_end: datetime
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                ifNull(nullIf(toString({service_col}), ''), 'unknown') AS service_name,
                count() AS log_count,
                countDistinct(pod_name) AS pods,
                countDistinct(container_name) AS containers
            FROM {self.settings.clickhouse_database}.{self.settings.logs_table}
            WHERE timestamp >= %(window_start)s
              AND timestamp < %(window_end)s
            GROUP BY service_name
            ORDER BY log_count DESC
            LIMIT 200
        """
        rows = self.client.query(
            query,
            parameters={"window_start": window_start, "window_end": window_end},
        ).named_results()
        return [dict(row) for row in rows]

    def query_log_baseline(
        self,
        service_col: str,
        baseline_start: datetime,
        window_start: datetime,
        window_minutes: int,
    ) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                service_name,
                avg(log_count) AS baseline_avg,
                stddevPop(log_count) AS baseline_std,
                count() AS baseline_points
            FROM (
                SELECT
                    ifNull(nullIf(toString({service_col}), ''), 'unknown') AS service_name,
                    toStartOfInterval(toDateTime(timestamp), INTERVAL %(window_minutes)s MINUTE) AS bucket,
                    count() AS log_count
                FROM {self.settings.clickhouse_database}.{self.settings.logs_table}
                WHERE timestamp >= %(baseline_start)s
                  AND timestamp < %(window_start)s
                GROUP BY service_name, bucket
            )
            GROUP BY service_name
        """
        rows = self.client.query(
            query,
            parameters={
                "baseline_start": baseline_start,
                "window_start": window_start,
                "window_minutes": window_minutes,
            },
        ).named_results()
        return [dict(row) for row in rows]

    def query_metric_summary(self, window_start: datetime, window_end: datetime) -> list[dict[str, Any]]:
        query = f"""
            SELECT
                metric_name,
                count() AS samples,
                avg(metric_value) AS avg_value,
                quantile(0.95)(metric_value) AS p95_value,
                max(metric_value) AS max_value
            FROM {self.settings.clickhouse_database}.{self.settings.metrics_table}
            WHERE timestamp >= %(window_start)s
              AND timestamp < %(window_end)s
            GROUP BY metric_name
            ORDER BY samples DESC
            LIMIT 300
        """
        rows = self.client.query(
            query,
            parameters={"window_start": window_start, "window_end": window_end},
        ).named_results()
        return [dict(row) for row in rows]

    def insert_report(
        self,
        job_id: str,
        run_id: str,
        window_start: datetime,
        window_end: datetime,
        status: str,
        summary: str,
        prompt: str,
        model: str,
        anomalies_json: str,
        metrics_json: str,
    ) -> None:
        now = datetime.utcnow().replace(microsecond=0)
        self.client.insert(
            f"{self.settings.clickhouse_database}.analyzer_reports",
            [
                [
                    job_id,
                    run_id,
                    window_start,
                    window_end,
                    status,
                    summary,
                    prompt,
                    model,
                    anomalies_json,
                    metrics_json,
                    now,
                ]
            ],
            column_names=[
                "job_id",
                "run_id",
                "window_start",
                "window_end",
                "status",
                "summary",
                "prompt",
                "model",
                "anomalies_json",
                "metrics_json",
                "created_at",
            ],
        )

    def insert_knowledge(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        payload = [
            [
                row["job_id"],
                row["run_id"],
                row["service_name"],
                row["signal_type"],
                row["insight"],
                float(row["confidence"]),
                row["created_at"],
            ]
            for row in rows
        ]
        self.client.insert(
            f"{self.settings.clickhouse_database}.analyzer_knowledge",
            payload,
            column_names=[
                "job_id",
                "run_id",
                "service_name",
                "signal_type",
                "insight",
                "confidence",
                "created_at",
            ],
        )
