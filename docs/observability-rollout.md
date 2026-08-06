# Rolling Out This Observability Approach Across Hundreds of Services

This repo's local stack (Vector → ClickHouse → Grafana, plus grafana-operator-managed CRDs) proves the pattern on one service. This doc covers what changes to run it across an org with hundreds of services.

## Architecture at scale

- **Instrumentation is a shared library, not a per-team decision.** Every service links a thin internal SDK wrapping the OpenTelemetry SDK (metrics + traces + logs) with sane defaults baked in: resource attributes (`service.name`, `service.namespace`, `service.version`, `deployment.environment`) auto-populated from the platform (k8s downward API / CI metadata), a standard HTTP/gRPC middleware that emits RED-style metrics automatically, and a golden-signal convention teams opt into rather than reinvent (`http.server.duration`, `http.server.request.count`, in-flight/queue-depth gauges for saturation).
- **Collection moves from "one Vector agent hand-wired per pipeline" to an OpenTelemetry Collector per node/cluster (DaemonSet) + a central Gateway Collector tier.** The node-level Collector does cheap local work (batching, resource detection, basic filtering); the Gateway tier does the expensive/central work (tail-based sampling for traces, cardinality enforcement, routing to backends). This repo's Vector→ClickHouse pipeline is fine for one service; at hundreds of services, Vector's static `prometheus_scrape` endpoint list (what we just extended by hand for `log-analyzer`) does not scale — the Collector uses k8s service discovery (`prometheus.io/scrape` annotations or a `PodMonitor`-equivalent) so onboarding a new service requires zero central config changes.
- **Storage is pluggable behind the Collector, not hardcoded to ClickHouse.** Keep ClickHouse (or swap for Mimir/Tempo/Loki, or a vendor) as an OTLP-speaking backend behind the Gateway Collector's exporter config. Application code and the node-level Collector never know or care what's behind the Gateway.

## Vendor neutrality

- Instrumentation uses **OpenTelemetry APIs/semantic conventions exclusively** — no direct Prometheus client library calls, no vendor SDKs in application code. This is what makes swapping ClickHouse for Grafana Cloud, Datadog, or a Prometheus/Mimir stack a Collector exporter-config change, not a re-instrumentation project.
- Dashboards and alerts are defined against **logical metric names and semantic-convention labels**, not backend-specific query syntax where avoidable. Where a backend-specific query is unavoidable (e.g. the ClickHouse SQL in this repo's `GrafanaDashboard`/`GrafanaAlertRuleGroup` CRs), it's isolated to the dashboard/alert layer, not baked into application code.
- Grafana itself (not the specific TSDB) is the vendor-neutral seam users interact with — datasources change, dashboards/alert-rule CRDs largely don't.

## Centralized cardinality and relabeling policy

- **Label allowlists enforced at the Gateway Collector**, not left to convention. A central policy (versioned, code-reviewed like any other config) defines: which resource/metric labels are always allowed (`service.name`, `route`, `method`, `status_class` — not raw `status` if that's high-cardinality per-service, not user IDs, not raw URLs/run IDs as label values — those belong in exemplars/traces, not metric labels).
- **Route templating is mandatory, not optional**: `/runs/{id}` must never appear as `/runs/8f3a...` in a label — the middleware in the shared SDK normalizes path params before the metric is even emitted, and the Collector's `transform`/`filter` processors reject metrics with label values matching ID-shaped patterns as a backstop.
- **Per-team/per-namespace cardinality budgets** enforced via Collector processors (drop or aggregate-away label dimensions beyond budget) with alerting on budget approach, so one team's high-cardinality mistake doesn't take down shared storage or blow the shared bill.
- Relabeling rules live in one central, reviewed repo (mirroring how `deploy/apps/values.yaml` centrally declares what gets deployed here) — teams can request new labels via PR, not by unilaterally emitting them.

## Alerting and noise reduction

- **Alerts are defined per-service against golden signals** (latency, traffic, errors, saturation) using the same instrumentation contract everywhere, so a shared alert-rule *template* (parameterized by `service.name`, thresholds, eval window — exactly the pattern used in this repo's `GrafanaAlertRuleGroup`) can be stamped out per service instead of hand-authored per team.
- **SLO-based alerting over raw thresholds** where practical: burn-rate alerts against an error-budget (multi-window, multi-burn-rate à la Google SRE) cut noise dramatically vs. static "error rate > X%" rules, especially for lower-traffic services where a static threshold either never fires or fires on noise.
- **Grouping and inhibition at the routing layer** (Alertmanager or Grafana's unified alerting): group by `service.name`/`team` so a dependency outage doesn't page 40 downstream teams individually; inhibit downstream symptom alerts when the root-cause alert is already firing.
- **Ownership routing driven by the same resource attributes used for cardinality control** (`service.namespace`/team label) — alert routing config is generated from the service catalog, not hand-maintained per alert rule.
- **Every alert requires a runbook link and a severity that maps to an actual response expectation** (page vs. ticket vs. dashboard-only) — enforced at alert-authoring time (schema/lint check in CI on the alert-rule repo), so alert fatigue is a CI-time problem, not a 3am problem.
