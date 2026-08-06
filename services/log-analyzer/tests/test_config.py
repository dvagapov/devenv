from log_analyzer.config import Settings

ENV_VARS = [
    "CLICKHOUSE_HOST",
    "CLICKHOUSE_PORT",
    "CLICKHOUSE_USER",
    "CLICKHOUSE_PASSWORD",
    "CLICKHOUSE_DATABASE",
    "RUNS_TABLE",
    "HTTP_HOST",
    "HTTP_PORT",
    "RUN_MIN_DURATION_SECONDS",
    "RUN_MAX_DURATION_SECONDS",
    "RUN_FAILURE_RATE",
    "RUN_MAX_CONCURRENCY",
]


def test_defaults(monkeypatch):
    for var in ENV_VARS:
        monkeypatch.delenv(var, raising=False)

    settings = Settings.from_env()

    assert settings.clickhouse_host == "localhost"
    assert settings.clickhouse_port == 8123
    assert settings.clickhouse_database == "observability"
    assert settings.runs_table == "api_runs"
    assert settings.http_port == 8000
    assert settings.run_failure_rate == 0.1
    assert settings.run_max_concurrency == 5


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_HOST", "ch.example.com")
    monkeypatch.setenv("HTTP_PORT", "9001")
    monkeypatch.setenv("RUN_FAILURE_RATE", "0.75")
    monkeypatch.setenv("RUN_MAX_CONCURRENCY", "42")

    settings = Settings.from_env()

    assert settings.clickhouse_host == "ch.example.com"
    assert settings.http_port == 9001
    assert settings.run_failure_rate == 0.75
    assert settings.run_max_concurrency == 42


def test_blank_env_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("CLICKHOUSE_HOST", "   ")
    settings = Settings.from_env()
    assert settings.clickhouse_host == "localhost"
