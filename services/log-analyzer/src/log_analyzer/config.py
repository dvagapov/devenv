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
    logs_table: str
    metrics_table: str
    service_column: str
    analyzer_job_id: str
    analyzer_interval_seconds: int
    analyzer_window_minutes: int
    anomaly_zscore_threshold: float
    llm_api_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_url)


    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            clickhouse_host=_env_str("CLICKHOUSE_HOST", "localhost"),
            clickhouse_port=_env_int("CLICKHOUSE_PORT", 8123),
            clickhouse_user=_env_str("CLICKHOUSE_USER", "default"),
            clickhouse_password=_env_str("CLICKHOUSE_PASSWORD", "clickhouse"),
            clickhouse_database=_env_str("CLICKHOUSE_DATABASE", "observability"),
            logs_table=_env_str("LOGS_TABLE", "vector_logs"),
            metrics_table=_env_str("METRICS_TABLE", "vector_metrics"),
            service_column=_env_str("SERVICE_COLUMN", "AUTO"),
            analyzer_job_id=_env_str("ANALYZER_JOB_ID", "hourly-system-health"),
            analyzer_interval_seconds=_env_int("ANALYZER_INTERVAL_SECONDS", 3600),
            analyzer_window_minutes=_env_int("ANALYZER_WINDOW_MINUTES", 60),
            anomaly_zscore_threshold=_env_float("ANOMALY_ZSCORE_THRESHOLD", 3.0),
            llm_api_url=_env_str("LLM_API_URL", ""),
            llm_api_key=_env_str("LLM_API_KEY", ""),
            llm_model=_env_str("LLM_MODEL", "gpt-4o-mini"),
            llm_timeout_seconds=_env_int("LLM_TIMEOUT_SECONDS", 30),
        )
