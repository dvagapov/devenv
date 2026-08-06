# Local Environment

> Compact reference. See [`../CLAUDE.md`](../CLAUDE.md) for repo conventions and layout rationale.

## Stack

k3d (1 node) + local Docker registry (`localhost:5000`) + ArgoCD, provisioned by OpenTofu — including installing the app-of-apps chart, so `tofu apply` alone gets ArgoCD managing all 8 Applications. Sync order: kube-state-metrics → clickhouse-operator → clickhouse → vector → grafana → log-analyzer → grafana-operator → grafana-monitoring (`syncWave` in `deploy/apps/values.yaml`).

Prereqs: macOS ARM64, Docker Desktop running.

## 1. Install tools

```bash
./scripts/install-tools-macos-arm64.sh
```
Installs: opentofu, kubectl, helm, k3d, argocd, jq, yq, k9s, kubectx.

## 2. Register ArgoCD repo credentials (private repo)

`deploy/apps/values.yaml`'s `argocd.repoURL` points at this repo over SSH. ArgoCD's repo-server needs its own credentials to clone it — your local git credentials aren't visible inside the cluster. One-time, before (or right after) the next step:

```bash
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic repo-hiring-platform -n argocd \
  --from-file=sshPrivateKey="$HOME/.ssh/id_ed25519" \
  --from-literal=type=git \
  --from-literal=url=git@github.com:apify-hiring/hiring-platform-danil-vagapov.git \
  --dry-run=client -o yaml | kubectl label -f - --local -o yaml argocd.argoproj.io/secret-type=repository | kubectl apply -f -
```
Use a scoped deploy key instead of your main key if you'd rather not put your personal key in a cluster secret, even a local one. Skip this on a fork with a public repo.

## 3. Provision cluster + ArgoCD + apps

```bash
cd terraform && tofu init && tofu apply
```
This one command: creates the k3d cluster `dev` (var `cluster_name`) + registry at `localhost:5000` (var `registry_port`), installs ArgoCD in ns `argocd` (var `argocd_chart_version`), runs `helm dependency update` on every chart under `deploy/charts/*/`, and installs `deploy/apps` (generating the 8 ArgoCD `Application` CRs). Safe to re-run — every step is idempotent. Vars in `terraform/variables.tf`.

```bash
kubectl -n argocd get applications          # watch sync/health
```
`log-analyzer` will show `ImagePullBackOff`/degraded until the next step — expected on a first run.

## 4. Build + push the app image

```bash
docker build -t localhost:5000/log-analyzer:dev services/log-analyzer
docker push localhost:5000/log-analyzer:dev
```
Push from the Mac uses `localhost:5000` (the registry's published port). **Pods pull using a different hostname**: `k3d-dev-registry:5000` — that's the only hostname k3d wires into each node's containerd mirror config (`--registry-use` at cluster create). Same registry, same image bytes, two hostnames for two network contexts. The chart already uses the cluster-side name — see `deploy/charts/log-analyzer/values.yaml` (`image.repository`/`image.tag`). If `registry_name`/`registry_port` vars change, update both the push command and the chart value.

ArgoCD's `log-analyzer` app has `selfHeal: true`, so once the image lands it'll pick it up on its own (or force it: `kubectl -n argocd annotate application log-analyzer argocd.argoproj.io/refresh=hard --overwrite`).

## 5. Access

| What | Command | Default creds |
|---|---|---|
| Grafana | `kubectl port-forward svc/grafana 3000:80 -n observability` | admin/admin (`deploy/charts/grafana/values.yaml`) |
| ClickHouse HTTP | `kubectl port-forward svc/clickhouse-clickhouse-headless 8123:8123 -n observability` | default/clickhouse |
| Runs API | `kubectl port-forward svc/log-analyzer 8000:8000 -n observability` | — |
| ArgoCD UI | `kubectl port-forward svc/argocd-server 8080:443 -n argocd` | `argocd admin initial-password -n argocd` |

Dashboard: Grafana → Dashboards → folder **Runs API** → "Runs API Golden Signals" (`deploy/charts/grafana-monitoring/templates/dashboards/golden-signals.yaml` — generic, one dashboard per entry in `values.yaml`'s `services:` list).
Alerts: Grafana → Alerting → Alert rules → folder **Runs API** (`deploy/charts/grafana-monitoring/templates/monitors/` — one file per golden signal: `errors.yaml`, `latency.yaml`, `saturation.yaml`, `availability.yaml`, each looping over `services:` too). Onboard a new service by adding an entry to `services:`, not by copying templates.
Datasource: Grafana → Connections → Data sources → **ClickHouse** (`deploy/charts/grafana-monitoring/templates/datasource.yaml` — the single source for both metrics and logs behind every dashboard/alert here).

Scripted check instead of clicking around: `./scripts/verify-grafana.sh` (lists datasources/dashboards/alert rules, fails if any are empty). Full UI walkthrough + how to configure notifications: **[docs/grafana-guide.md](grafana-guide.md)**.

## 6. Generate load / failures

```bash
python services/log-analyzer/scripts/load_test.py --base-url http://localhost:8000 \
  --requests 300 --concurrency 30 --rps 20
```
Tune before starting the pod (env vars on the `log-analyzer` Deployment, or locally via `.env`):
`RUN_FAILURE_RATE` (0–1), `RUN_MIN_DURATION_SECONDS`, `RUN_MAX_DURATION_SECONDS`, `RUN_MAX_CONCURRENCY`.
Push `RUN_FAILURE_RATE` up and/or exceed `RUN_MAX_CONCURRENCY` with concurrency to trip the alert rules (`deploy/charts/grafana-monitoring/templates/monitors/`). For deterministic per-alert scenarios (not dependent on the randomized failure rate) use `scripts/trigger_alerts.py errors|latency|saturation|all` instead — see `services/log-analyzer/README.md`.

## 7. Tests

```bash
cd services/log-analyzer
pip install -r requirements-dev.txt
pytest tests/
```
Unit + smoke tests against an in-memory fake ClickHouse store — no cluster needed.

## 8. Run the API without k8s

```bash
cd services/log-analyzer
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env && export $(cat .env | xargs)   # point CLICKHOUSE_HOST at a reachable instance
PYTHONPATH=src python -m log_analyzer.main            # serves :8000
```

## 9. Teardown

```bash
cd terraform && tofu destroy
```

## Chart map

| Path | What |
|---|---|
| `deploy/apps` | app-of-apps — generates ArgoCD `Application` CRs |
| `deploy/charts/log-analyzer` | Runs API Deployment/Service |
| `deploy/charts/clickhouse-operator` | installs the operator (`ClickHouseCluster`/`ClickHouseKeeperCluster` CRDs) |
| `deploy/charts/clickhouse-cluster` | the actual ClickHouse deploy — CRs + bootstrap Job. Service: `clickhouse-clickhouse-headless`. Schema (`observability` DB: `vector_logs`, `vector_metrics`, `api_runs`) lives in this chart's `values.yaml` (`bootstrap.sql`) |
| `deploy/charts/vector` | scrapes `/metrics` (kube-state-metrics + log-analyzer) + tails container logs → ClickHouse |
| `deploy/charts/grafana` | Grafana instance + plugin install only — no datasource/dashboards baked in |
| `deploy/charts/grafana-operator` | wraps upstream `grafana-operator` chart |
| `deploy/charts/grafana-monitoring` | `Grafana` (external instance CR) + `GrafanaDatasource` (ClickHouse) + `GrafanaDashboard` + `GrafanaAlertRuleGroup` + `GrafanaFolder`, generic/`services:`-driven |
| `deploy/charts/kube-state-metrics` | k8s object metrics |
