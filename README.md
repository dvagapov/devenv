# Apify Platform Reliability Challenge — Solution

Solution to the challenge in [`task_README.md`](task_README.md): a dummy Runs API (simulated web-scraping jobs), instrumented with golden-signal metrics, shipped to Grafana via ClickHouse, with dashboards and alert rules, deployed to a local Kubernetes cluster via ArgoCD.

## What's here

- **`services/log-analyzer`** — the Runs API (FastAPI/Python). `POST /runs`, `GET /runs/{id}`, `/health`, `/health/live`, `/metrics`. Simulated runs fail/slow down on configurable, randomized rates (env vars), plus deterministic `forceFail`/`forceSlowMs` request overrides for testing alerts on demand.
- **`deploy/`** — one Helm chart per component (ClickHouse, Vector, Grafana, grafana-operator, the app itself), wired together by an ArgoCD app-of-apps (`deploy/apps`). See [`docs/local-environment.md`](docs/local-environment.md#chart-map) for the full chart map.
- **`terraform/`** — provisions the local cluster (k3d + local registry + ArgoCD) end to end.
- **`docs/`** — setup, Grafana usage, and the production rollout spec (below).
- **`CLAUDE.md`** — repo conventions and a list of non-obvious bugs found and fixed while building this, for anyone (human or AI) picking the repo back up.

### Metrics/logs pipeline

```
log-analyzer  --/metrics (Prometheus)-->  Vector  --> ClickHouse (vector_metrics, vector_logs, api_runs)
                                                            |
                                                            v
                                              Grafana (GrafanaDatasource CRD)
                                                            |
                                              GrafanaDashboard + GrafanaAlertRuleGroup CRDs
                                              (grafana-operator, per deploy/charts/grafana-monitoring)
```

No standalone Prometheus/Alertmanager is deployed — Vector scrapes `/metrics` directly and ships to ClickHouse; Grafana queries ClickHouse for both metrics and logs; alert rules are Grafana-native (matches the challenge's requirement 4: definitions only, no real routing required).

## Mapping to the task's requested layout

[`task_README.md`](task_README.md) asks for `./src`, `./deploy`, `./monitoring`. This repo instead builds on a pre-existing local-dev template (see [`CLAUDE.md`](CLAUDE.md) for why) — the equivalents:

| Task asks for | This repo | Contains |
|---|---|---|
| `./src` (app code + load generator) | [`services/log-analyzer`](services/log-analyzer) | FastAPI app (`src/`), load/failure generators (`scripts/load_test.py`, `scripts/trigger_alerts.py`) |
| `./deploy` (deployment artifacts) | [`deploy/`](deploy) | Already matches — one Helm chart per component + the ArgoCD app-of-apps |
| `./monitoring` (dashboards, alerts, monitoring artifacts) | [`deploy/charts/grafana-monitoring`](deploy/charts/grafana-monitoring) | `GrafanaDatasource`, `GrafanaDashboard`, `GrafanaAlertRuleGroup`, `GrafanaFolder` CRDs — dashboards under `templates/dashboards/`, alert rules under `templates/monitors/` (one file per golden signal) |

## Quick start

Full step-by-step instructions, including a private-repo ArgoCD credentials step and known local-registry/hostname gotchas: **[docs/local-environment.md](docs/local-environment.md)**.

```bash
./scripts/install-tools-macos-arm64.sh          # opentofu, kubectl, helm, k3d, argocd, jq, yq, k9s, kubectx
cd terraform && tofu init && tofu apply         # cluster + registry + ArgoCD + the full app-of-apps
docker build -t localhost:5000/log-analyzer:dev services/log-analyzer && docker push localhost:5000/log-analyzer:dev
```

## Generating load and failures

```bash
python services/log-analyzer/scripts/load_test.py --base-url http://localhost:8000 --requests 300 --concurrency 30 --rps 20
```
Randomized failure rate/duration via env (`RUN_FAILURE_RATE`, `RUN_MIN_DURATION_SECONDS`, `RUN_MAX_DURATION_SECONDS`, `RUN_MAX_CONCURRENCY`). For deterministic, targeted alert scenarios instead of waiting on randomness:
```bash
python services/log-analyzer/scripts/trigger_alerts.py errors|latency|saturation|all
```
Details: [`services/log-analyzer/README.md`](services/log-analyzer/README.md).

## Viewing dashboards and alerts

```bash
kubectl port-forward svc/grafana 3000:80 -n observability   # admin/admin
```
Dashboard: **Dashboards → Runs API → Runs API Golden Signals** (traffic, errors, latency, saturation, health-check availability, plus recent runs and recent logs — all from the one ClickHouse datasource, metrics and logs alike).
Alerts: **Alerting → Alert rules → Runs API** (5 rules: high failure rate, no successful runs, high latency, high saturation, health-check failing).

Scripted check instead of clicking around: `./scripts/verify-grafana.sh` — confirms the datasource, dashboard, and alert rules actually exist and are non-empty, not just that the CRDs were applied.

Full UI walkthrough + how to configure real notification routing (contact points/policies): **[docs/grafana-guide.md](docs/grafana-guide.md)**.

## Tests

```bash
cd services/log-analyzer && pip install -r requirements-dev.txt && pytest tests/
```
Unit + smoke tests (full run lifecycle, health-endpoint split, metrics) against an in-memory fake ClickHouse store — no cluster required.

## Production rollout spec

How this would scale to hundreds of services — architecture, vendor neutrality, centralized cardinality/relabeling, alerting/noise reduction: **[docs/observability-rollout.md](docs/observability-rollout.md)**.

## Troubleshooting and future work

- **[docs/troubleshoot.md](docs/troubleshoot.md)** — symptom → diagnosis → fix for every real issue hit while building this, including several that are version-pinned behavior worth re-checking after a ClickHouse/Vector/grafana-operator upgrade.
- **[docs/improvements.md](docs/improvements.md)** — what's deliberately cut or approximated for this scope: security hardening, correctness gaps (e.g. approximated latency, no HA), CI/operational gaps, refactoring, and unattempted features.

## AI usage

Built with Claude Code (Anthropic), used extensively throughout — architecture decisions, all application/Helm/Terraform code, debugging live cluster issues, and this documentation. Notable example of the human-in-the-loop process: several real, non-obvious bugs (a Vector timestamp-precision mismatch that silently corrupted every metrics/logs row, two separate Grafana ClickHouse-plugin field-name mismatches — one on the datasource config, one on every dashboard panel's query target — an ArgoCD Server-Side-Apply requirement for an oversized CRD, a cross-namespace resource collision) were found by deploying to a real cluster and reading actual logs/API responses, not assumed away — see the "Key facts" bullets in [`CLAUDE.md`](CLAUDE.md) for the specifics and why each fix is what it is.
