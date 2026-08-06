# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repo.

## What this repo is

Solution to the Apify Platform Reliability Challenge (task spec: [`task_README.md`](task_README.md); solution overview: [`README.md`](README.md)): a dummy runs-simulation API, instrumented, shipped to Grafana, with dashboards + alert templates, deployed to a local k8s cluster via ArgoCD.

## Layout (deviates from task_README.md's suggested `./src` / `./deploy` / `./monitoring`)

This repo uses a pre-existing local-dev template instead. task_README.md's `./src` guidance maps to `services/`; there is no separate `./monitoring` dir — monitoring artifacts live inside `deploy/charts/grafana-monitoring` (see below). This was a deliberate choice, not an oversight.

```
services/log-analyzer/   Runs API (FastAPI). App code in src/, load generator in scripts/load_test.py.
deploy/apps/              Helm chart generating ArgoCD Application CRs (app-of-apps).
deploy/charts/*/          One Helm chart per component. Independently versioned.
scripts/                  Local machine setup (macOS ARM64 tool install).
terraform/                Provisions k3d cluster + local registry + ArgoCD.
docs/                     Compact reference docs (start with docs/local-environment.md).
```

Full local-environment run/deploy instructions: **[docs/local-environment.md](docs/local-environment.md)**.
Checking Grafana (UI walkthrough + configuring notifications): **[docs/grafana-guide.md](docs/grafana-guide.md)**.
Symptom → diagnosis → fix for every bug below (fuller writeups, re-check after upgrading ClickHouse/Vector/grafana-operator): **[docs/troubleshoot.md](docs/troubleshoot.md)**.
What's deliberately cut/approximated for this scope: **[docs/improvements.md](docs/improvements.md)**.

## Key facts to hold in context

- Metrics pipeline: app exposes Prometheus `/metrics` → Vector scrapes (`deploy/charts/vector`) → ClickHouse (`observability.vector_metrics`, `observability.api_runs`) → Grafana queries via `grafana-clickhouse-datasource`. No standalone Prometheus server is deployed.
- The `grafana-clickhouse-datasource` plugin (v4.x) reads its server address from `jsonData.host`/`jsonData.port`/`jsonData.protocol` — **not** a top-level `url` field. Setting `url` is silently ignored (no validation error at apply time) and produces `[config] invalid server host` at query time instead — confirmed live. `templates/datasource.yaml` uses `host`/`port`/`protocol`; don't "simplify" it back to a `url` field even though that's the more common datasource-provisioning shape elsewhere in Grafana.
- Same plugin's panel/query target schema is `{"queryType": "sql", "rawSql": "..."}` — a bare `"query": "..."` field (an easy mistake, since it reads naturally and some other datasources use exactly that shape) is silently not recognized, so the plugin sends an empty query string and ClickHouse returns `Code: 62. DB::Exception: Empty query.` with no indication the field name was wrong. Every panel in `templates/dashboards/golden-signals.yaml` uses `rawSql`/`queryType` now — the alert rules (`templates/monitors/*.yaml`) already did, which is what exposed the panels having drifted from that format.
- Datasources/dashboards/alerts are **not** baked into the Grafana Helm chart (`deploy/charts/grafana` only stands up the instance + installs the `grafana-clickhouse-datasource` plugin, which isn't manageable via CRD). They're `GrafanaDatasource`/`GrafanaDashboard`/`GrafanaAlertRuleGroup` CRDs shipped by the `grafana-monitoring` ArgoCD app, reconciled by `grafana-operator` against the existing Grafana instance in **external** mode (`deploy/charts/grafana-monitoring/templates/grafana-instance.yaml`). The ClickHouse datasource (`templates/datasource.yaml`, uid `clickhouseDatasourceUid` in values) is the single backing source for both metrics and logs across every dashboard/alert — don't add a second datasource definition anywhere else (the old file-provisioned one in the grafana chart was removed specifically to avoid two owners of the same uid).
- `grafana-monitoring` is a generic template, not log-analyzer-specific: `values.yaml` has a `services:` list (each entry just needs `name`; everything else — thresholds, metric names, ClickHouse table, health check path, max concurrency — falls back to `values.yaml`'s `defaults:`, deep-merged per service via the `grafana-monitoring.svcConfig` helper in `templates/_helpers.tpl`). Onboard a new service by adding a `services:` entry, not by copying/editing templates. One `GrafanaDashboard` + one `GrafanaFolder` + 4 `GrafanaAlertRuleGroup` (one per golden signal, each its own file under `templates/monitors/`: `errors.yaml`, `latency.yaml`, `saturation.yaml`, `availability.yaml`) are generated per service.
- `GrafanaAlertRuleGroup.folderRef` (name-based folder lookup) is broken on the installed grafana-operator version — always use `folderUID` referencing a `GrafanaFolder` with an explicit `spec.uid` set (see `templates/monitors/folder.yaml`). Don't revert to `folderRef`.
- Grafana's DB is persisted (`deploy/charts/grafana/values.yaml`, `persistence.enabled: true`) — it defaults to ephemeral SQLite, so a pod restart used to wipe every folder/dashboard/alert. Don't drop that setting: `GrafanaAlertRuleGroup` in particular doesn't proactively re-push after external data loss (its own spec/hash hasn't changed, so grafana-operator sees nothing to do) — a wipe silently leaves zero alert rules until something touches the CR again.
- The availability/synthetic-check monitor is derived from `http_requests_total{route=healthCheckPath}` (a delta over the window, since it's a raw cumulative counter), not an active external prober — none is deployed. The app's metrics middleware (`services/log-analyzer/src/log_analyzer/api.py`) deliberately still counts `/health` and `/health/live` in `http_requests_total` while excluding them from the latency histogram (probe traffic would skew percentiles) — don't move them back to being excluded from both, the availability monitor depends on the counter data.
- ArgoCD app-of-apps sync order matters — see `syncWave` in `deploy/apps/values.yaml` (kube-state-metrics → clickhouse-operator → clickhouse → vector → grafana → log-analyzer → grafana-operator → grafana-monitoring).
- Vector's histogram handling: Prometheus histograms don't map to a scalar `.gauge`/`.counter` value, so `deploy/charts/vector/values.yaml` derives `<metric>_sum`/`<metric>_count` series specifically so latency can be computed downstream. Don't "simplify" that transform without preserving this.
- Vector's ClickHouse sinks use `encoding.timestamp_format: unix_ns` — the `vector_logs`/`vector_metrics` tables are `DateTime64(9)` (nanosecond precision). This isn't the obvious/default choice (`unix` = seconds is what most examples use) — `unix` was the original value and silently corrupted every row's timestamp to 1970-01-01 (a bare Unix-seconds integer written into a nanosecond column reads as ~1 second past epoch), which both mis-partitioned the tables and made the 7-day TTL delete rows almost immediately, so every dashboard panel and alert query against these tables showed "No Data" with zero visible errors anywhere. If either table's precision ever changes, this must change with it.
- Helm chart pattern to copy for a new component: `deploy/charts/grafana-monitoring` (self-authored, own `templates/`) or `deploy/charts/grafana` (thin wrapper around an upstream chart dependency).
- Local registry has two hostnames depending on where you are: `localhost:5000` from the Mac (docker build/push), `k3d-dev-registry:5000` from inside the cluster (what chart `image.repository` fields must use — k3d's containerd mirror only rewrites the registry's own container hostname, not `localhost`).
- ClickHouse is deployed by `deploy/charts/clickhouse-cluster` (via `clickhouse-operator`'s CRs — `ClickHouseCluster`/`ClickHouseKeeperCluster`), **not** a plain StatefulSet chart. Its Service is `clickhouse-clickhouse-headless.observability.svc.cluster.local:8123` (headless — `<cluster.name>-clickhouse-headless`, `cluster.name` from `deploy/charts/clickhouse-cluster/values.yaml`). Schema/DB bootstrap (the `observability` DB, `vector_logs`/`vector_metrics`/`api_runs` tables) lives in that same chart's `values.yaml` under `bootstrap.sql`, run once by a Job on deploy — not in a `deploy/charts/clickhouse` chart (that name doesn't exist; a stale duplicate under that path was deleted after it caused a real outage — every consumer had been pointed at a `clickhouse.observability...` hostname that was never actually deployed).

## Conventions

- Chart naming/labels: every self-authored chart has `templates/_helpers.tpl` with `<chart>.name` / `<chart>.fullname` / `<chart>.labels` / `<chart>.selectorLabels`, copy that pattern exactly for new charts.
- **Always pass `-n observability`** (or `--namespace`) on any manual `kubectl apply`/`create` against `grafana-monitoring`'s CRDs. `GrafanaFolder`/`GrafanaDashboard`/`GrafanaAlertRuleGroup`'s `instanceSelector` matches `Grafana` CRs **cluster-wide by label, not by namespace** — a manifest applied without a namespace lands in `default` and grafana-operator will try to reconcile it against every matching `Grafana` instance it finds anywhere, including the real one, causing spurious "found matching instances: 2" / intermittent `Secret "grafana" not found` errors that look like operator flakiness but are actually stray resources in the wrong namespace. `./scripts/verify-grafana.sh` won't catch this (it only inspects Grafana's own state) — `kubectl get grafana,grafanafolder,grafanadashboard,grafanaalertrulegroup -A` will.
- Env config in Python services: `Settings` frozen dataclass with `from_env()`, using the `_env_str/_env_int/_env_float` helpers already in `services/log-analyzer/src/log_analyzer/config.py` — reuse this pattern for any new service.
- Sprig in Helm templates: use `mulf`/`divf`/`addf` for float values, not `mul`/`div`/`add` (those truncate to int — caused a real bug in the alert thresholds, since fixed).
- No Prometheus/Alertmanager deployed — alert rules are defined as Grafana CRDs, not wired to real routing (per task requirement 4).

## Rollout spec

`docs/observability-rollout.md` is the "how would this scale to hundreds of services" writeup (task requirement 3). Read it before proposing changes to the metrics/instrumentation architecture — it documents intended direction (OTel Collector, cardinality budgets, SLO-based alerting) that this repo's local stack only partially implements.
