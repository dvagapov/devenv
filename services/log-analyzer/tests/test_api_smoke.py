from __future__ import annotations

import time


def test_health_live_has_no_dependency(client, fake_store):
    fake_store.healthy = False  # even if ClickHouse is down...
    resp = client.get("/health/live")
    assert resp.status_code == 200  # ...liveness must still pass


def test_health_ready_reflects_clickhouse(client, fake_store):
    assert client.get("/health").status_code == 200

    fake_store.healthy = False
    assert client.get("/health").status_code == 503


def test_get_unknown_run_is_404(client):
    resp = client.get("/runs/does-not-exist")
    assert resp.status_code == 404


def test_run_lifecycle_succeeds(client):
    created = client.post("/runs", json={"input": {"url": "https://example.com"}})
    assert created.status_code == 201
    body = created.json()
    assert body["status"] == "READY"
    run_id = body["id"]

    final = None
    for _ in range(50):
        got = client.get(f"/runs/{run_id}")
        assert got.status_code == 200
        if got.json()["status"] in ("SUCCEEDED", "FAILED"):
            final = got.json()
            break
        time.sleep(0.05)

    assert final is not None, "run did not finish in time"
    assert final["status"] == "SUCCEEDED"  # RUN_FAILURE_RATE=0 in test env
    assert final["durationSeconds"] is not None


def test_force_fail_override(client):
    created = client.post("/runs", json={"forceFail": True})
    run_id = created.json()["id"]

    final = None
    for _ in range(50):
        got = client.get(f"/runs/{run_id}").json()
        if got["status"] in ("SUCCEEDED", "FAILED"):
            final = got
            break
        time.sleep(0.05)

    assert final is not None
    assert final["status"] == "FAILED"


def test_force_slow_delays_response(client):
    start = time.perf_counter()
    client.post("/runs", json={"forceSlowMs": 150})
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.15


def test_health_counted_in_requests_but_not_duration(client):
    client.get("/health")
    client.get("/health/live")

    body = client.get("/metrics").content.decode()

    assert 'http_requests_total{method="GET",route="/health",status="200"}' in body
    assert 'http_requests_total{method="GET",route="/health/live",status="200"}' in body
    # duration histogram must have no samples for these routes — they're excluded
    # so probe traffic doesn't skew latency stats.
    assert 'http_request_duration_seconds_count{method="GET",route="/health"}' not in body
    assert 'http_request_duration_seconds_count{method="GET",route="/health/live"}' not in body


def test_metrics_endpoint_exposes_run_counters(client):
    client.post("/runs", json={"input": {}})
    time.sleep(0.1)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"runs_total" in resp.content
    assert b"http_requests_total" in resp.content
