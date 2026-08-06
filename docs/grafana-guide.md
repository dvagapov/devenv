# Grafana: Checking the UI & Configuring Notifications

> Compact reference. See [`../CLAUDE.md`](../CLAUDE.md) for repo conventions, [`local-environment.md`](local-environment.md) for full deploy instructions.

## Access

```bash
kubectl port-forward svc/grafana 3000:80 -n observability
```
Open `http://localhost:3000`, login `admin` / `admin` (`deploy/charts/grafana/values.yaml`).

Scripted check instead of clicking around: `./scripts/verify-grafana.sh` — lists datasources/dashboards/alert rules and fails (non-zero exit) if any are missing or a dashboard has zero panels. Starts its own port-forward if Grafana isn't already reachable.

## What to look at

| Where | What you should see |
|---|---|
| **Connections → Data sources** | `ClickHouse` (uid `clickhouse-observability`), type `grafana-clickhouse-datasource`. Provisioned by `deploy/charts/grafana-monitoring/templates/datasource.yaml` (`GrafanaDatasource` CRD) — not by the Grafana Helm chart. |
| **Dashboards → Runs API** (folder) | "Runs API Golden Signals" — traffic/errors/latency/saturation panels (from `observability.vector_metrics`/`api_runs`) + a "Recent Logs" panel (from `observability.vector_logs`), all through the one ClickHouse datasource above. |
| **Alerting → Alert rules → Runs API** (folder) | 5 rules: high failure rate, no successful runs, high HTTP latency, high concurrency saturation, health check failing. Each shows an evaluation state (`Normal` / `Pending` / `Alerting` / `NoData`). |

Every dashboard/alert here is generated per entry in `deploy/charts/grafana-monitoring/values.yaml`'s `services:` list — see that chart's values for what's configurable per service.

## Triggering alerts to see them fire

`services/log-analyzer/scripts/trigger_alerts.py errors|latency|saturation|all` drives real alert conditions deterministically (see `services/log-analyzer/README.md`). After running it, watch **Alerting → Alert rules** — state moves `Normal` → `Pending` (condition true, waiting out the rule's `for:` duration) → `Alerting` (firing).

## Configuring notifications

This repo intentionally does **not** wire up real alert routing (matches the challenge's requirement 4 — alert *definitions* are enough, Alertmanager/routing isn't required). To wire it up for real in Grafana's own unified alerting (no separate Alertmanager needed):

1. **Alerting → Contact points → + Add contact point.** Pick an integration (Slack webhook, email, PagerDuty, webhook, etc.), fill in its target (e.g. Slack webhook URL), save. Use **Test** to fire a sample notification before relying on it.
2. **Alerting → Notification policies.** The default policy catches everything with no more specific match. To route by severity/service instead of catching everything:
   - **Edit** the default policy's contact point for a catch-all, or
   - **+ New nested policy** with a label matcher, e.g. `severity = critical` → a paging contact point, `service = log-analyzer` → a team channel. Every rule in `deploy/charts/grafana-monitoring/templates/monitors/` already sets `severity` and `service` labels (see `spec.rules[].labels` in any `monitors/*.yaml` file) — matchers can key off those directly, no rule changes needed.
3. **Mute timings** (Alerting → Mute timings) if you want to suppress notifications during a maintenance window without disabling the rule.

To make this durable/GitOps-managed rather than a manual UI change: `grafana-operator` also has `GrafanaContactPoint` and `GrafanaNotificationPolicy` CRDs (same pattern as `GrafanaDashboard`/`GrafanaAlertRuleGroup` in this chart) — add them under `deploy/charts/grafana-monitoring/templates/` following the existing `monitors/*.yaml` files as a template if/when real routing is needed.
