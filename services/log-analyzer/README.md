# log-analyzer (Runs API)

Dummy API service simulating Apify-style web-scraping "runs". Accepts a run request, executes it asynchronously with a configurable random duration and failure rate, and reports status. Instrumented with Prometheus-format metrics covering the golden signals (latency, traffic, errors, saturation).

## Endpoints

- `POST /runs` — start a simulated run. Body: `{"input": {...}}` (input is stored, not interpreted). Returns `{id, status, startedAt}`.
- `GET /runs/{id}` — current run status: `READY` → `RUNNING` → `SUCCEEDED`/`FAILED`.
- `GET /health` — readiness: 200 if ClickHouse is reachable, else 503.
- `GET /health/live` — liveness: 200 if the process is up. No dependency checks — a ClickHouse outage must not get the pod killed and restarted.
- `GET /metrics` — Prometheus exposition format.

## Run locally (no k8s)

```bash
cd services/log-analyzer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# point at a reachable ClickHouse (see ../../docs/local-environment.md to stand one up locally), or override via env
cp .env.example .env
export $(cat .env | xargs)

PYTHONPATH=src python -m log_analyzer.main
```

Service listens on `:8000` (`HTTP_PORT`).

## Run in Docker

```bash
docker build -t localhost:5000/log-analyzer:dev .
docker run --rm -p 8000:8000 \
  -e CLICKHOUSE_HOST=host.docker.internal \
  localhost:5000/log-analyzer:dev
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/
```

Unit tests (`test_config.py`, `test_metrics.py`) plus API smoke tests (`test_api_smoke.py`) that exercise the full `POST /runs` → background execution → `GET /runs/{id}` lifecycle, health endpoints, and `/metrics` output against an in-memory fake ClickHouse store (`tests/conftest.py`) — no real ClickHouse or k8s needed.

## Generate load and failures

Failure rate and run duration are configurable via env (`RUN_FAILURE_RATE`, `RUN_MIN_DURATION_SECONDS`, `RUN_MAX_DURATION_SECONDS`, `RUN_MAX_CONCURRENCY` — the concurrency cap drives the saturation signal once exceeded).

```bash
# bump failure rate before starting the service to trigger the HighErrorRate alert
export RUN_FAILURE_RATE=0.4

python scripts/load_test.py --base-url http://localhost:8000 --requests 300 --concurrency 30 --rps 20
```

### Deterministic alert-triggering scenarios

`load_test.py` uses the service's own randomized `RUN_FAILURE_RATE`, so tripping a specific alert deterministically means editing deployment env and waiting. `scripts/trigger_alerts.py` instead uses two test-only request overrides (`forceFail`, `forceSlowMs`, accepted by `POST /runs`, never used by real clients) to drive each golden-signal monitor in `deploy/charts/grafana-monitoring/templates/monitors/` (one file per signal: `errors.yaml`, `latency.yaml`, `saturation.yaml`, `availability.yaml`) on demand, against a service running with default config:

```bash
python scripts/trigger_alerts.py errors       # HighErrorRate + NoSuccessfulRuns
python scripts/trigger_alerts.py latency      # HighLatencyP95
python scripts/trigger_alerts.py saturation   # SaturationHigh
python scripts/trigger_alerts.py all          # runs all three in sequence
```

Each scenario sustains load for `--duration` seconds (default 360s) so the condition holds across the alert's `for:` window, not just a single spike — alerts still take a few minutes to actually fire even with this script.

Manual spot checks:

```bash
curl -s -X POST localhost:8000/runs -H "Content-Type: application/json" -d '{}' | jq
curl -s localhost:8000/runs/<id> | jq
curl -s localhost:8000/health
curl -s localhost:8000/metrics | head -30
```

## Deploying to the local cluster

Built as chart `deploy/charts/log-analyzer`, wired into ArgoCD via `deploy/apps/values.yaml` (see [`../../docs/local-environment.md`](../../docs/local-environment.md)). Push the image to the local registry (`localhost:5000/log-analyzer:dev`) before syncing.

## Dashboards & alerts

Metrics are scraped by Vector (`deploy/charts/vector`) and land in ClickHouse (`observability.vector_metrics`, `observability.api_runs`). Dashboard and alert-rule CRDs are shipped by the `grafana-monitoring` ArgoCD app (`deploy/charts/grafana-monitoring`) via `grafana-operator`. Open Grafana (`kubectl port-forward svc/grafana 3000:80 -n observability`), look under **Dashboards → Runs API Golden Signals** and **Alerting → Alert rules**.
