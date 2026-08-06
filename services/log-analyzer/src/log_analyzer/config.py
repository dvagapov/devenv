from __future__ import annotations

from dataclasses import dataclass
import os


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip() or default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return int(value)


@dataclass(frozen=True)
class Settings:
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_user: str
    clickhouse_password: str
    clickhouse_database: str
    runs_table: str
    http_host: str
    http_port: int
    run_min_duration_seconds: float
    run_max_duration_seconds: float
    run_failure_rate: float
    run_max_concurrency: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            clickhouse_host=_env_str("CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=_env_int("CLICKHOUSE_PORT", 8123),
            clickhouse_user=_env_str("CLICKHOUSE_USER", "default"),
            clickhouse_password=_env_str("CLICKHOUSE_PASSWORD", "clickhouse"),
            clickhouse_database=_env_str("CLICKHOUSE_DATABASE", "observability"),
            runs_table=_env_str("RUNS_TABLE", "api_runs"),
            http_host=_env_str("HTTP_HOST", "0.0.0.0"),
            http_port=_env_int("HTTP_PORT", 8000),
            run_min_duration_seconds=_env_float("RUN_MIN_DURATION_SECONDS", 1.0),
            run_max_duration_seconds=_env_float("RUN_MAX_DURATION_SECONDS", 8.0),
            run_failure_rate=_env_float("RUN_FAILURE_RATE", 0.1),
            run_max_concurrency=_env_int("RUN_MAX_CONCURRENCY", 5),
        )
