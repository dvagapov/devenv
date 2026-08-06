# Troubleshooting

Real issues hit while building/operating this stack, symptom-first. Several are version-pinned behavior (a specific ClickHouse/Vector/grafana-operator/plugin version did X) — re-check these specifically after bumping any of those versions, since the fix might silently stop applying or a new variant might appear.

## "No Data" on dashboard panels

Two independent causes hit in this repo; check both.

**1. ClickHouse tables have data, but not in the queried time range.**
```bash
kubectl exec -n observability clickhouse-clickhouse-0-0-0 -- clickhouse-client \
  --query "SELECT count(), min(timestamp), max(timestamp) FROM observability.vector_metrics"
```
If `min`/`max` show `1970-01-01`, the timestamp is corrupted at ingest, not missing. Root cause: Vector's ClickHouse sink `encoding.timestamp_format` must match the column's precision — `vector_logs`/`vector_metrics` are `DateTime64(9)` (nanosecond), so it must be `unix_ns`. `unix` (seconds) silently produces ~1-second-past-epoch timestamps, which both mis-partitions the table and makes the 7-day TTL delete the rows almost immediately — no errors anywhere, just empty tables a few minutes after ingest. See `deploy/charts/vector/values.yaml`. **Re-check after a Vector upgrade** if the sink's encoding options or defaults change.

**2. The datasource/query itself is broken (data exists and is recent, panel still empty).** Check Grafana's logs:
```bash
kubectl logs -n observability -l app.kubernetes.io/name=grafana --tail=200 | grep -i clickhouse
```
- `[config] invalid server host. Either empty or not set` → the `grafana-clickhouse-datasource` plugin (v4.x) reads the server address from `jsonData.host`/`port`/`protocol`, **not** a top-level `url` field (which most other Grafana datasource types use, so it's an easy default to reach for). See `deploy/charts/grafana-monitoring/templates/datasource.yaml`. **Re-check after a plugin upgrade** — the field name plugin ClickHouse uses has changed across major versions before.
- `Code: 62. DB::Exception: Empty query.` (from ClickHouse itself, via Grafana) → a dashboard panel target is using `{"query": "SELECT ..."}` instead of `{"queryType": "sql", "rawSql": "SELECT ..."}`. The plugin doesn't recognize a bare `query` field and sends nothing. All targets in `templates/dashboards/golden-signals.yaml` and `templates/monitors/*.yaml` must use `rawSql`/`queryType`.

Quick end-to-end check bypassing the dashboard entirely:
```bash
kubectl port-forward svc/grafana 3000:80 -n observability &
curl -s -u admin:admin -X POST http://localhost:3000/api/ds/query -H "Content-Type: application/json" -d '{
  "queries": [{"refId":"A","datasource":{"type":"grafana-clickhouse-datasource","uid":"clickhouse-observability"},
  "queryType":"sql","rawSql":"SELECT count() FROM observability.api_runs"}]
}'
```
A `frames[0].data.values` with real numbers means the datasource+query path works; if the dashboard still shows "No Data," the panel's own target JSON has drifted from this shape.

## Alert rules missing / zero alert rules in Grafana

```bash
./scripts/verify-grafana.sh
```
If it reports `alert_rules=0` (or dashboards/datasources=0) despite the CRDs existing (`kubectl get grafanaalertrulegroup -n observability`):

**Grafana's DB was wiped.** The community Grafana chart defaults to ephemeral SQLite — any pod restart/reschedule loses every folder/dashboard/alert-rule. `deploy/charts/grafana/values.yaml` sets `persistence.enabled: true` specifically to prevent this; if that ever gets reverted (or the PVC gets deleted), expect this again. Confirm: `kubectl get pvc -n observability | grep grafana`.

**grafana-operator doesn't proactively re-push after external data loss.** Even with persistence in place, if Grafana's DB is ever emptied out-of-band (e.g. you deleted the PVC, or restored from an older snapshot), `GrafanaAlertRuleGroup`/`GrafanaDashboard`/`GrafanaFolder` CRs whose spec/hash hasn't changed won't get re-synced until their `resyncPeriod` elapses (5m for folder/dashboard/alert groups in this chart) or you force it:
```bash
kubectl delete grafanaalertrulegroup log-analyzer-errors log-analyzer-latency log-analyzer-saturation log-analyzer-availability -n observability
helm template deploy/charts/grafana-monitoring | kubectl apply --server-side --force-conflicts -n observability -f -
```

## `folder with uid <x> not found` in an AlertRuleGroup's status

```bash
kubectl get grafanaalertrulegroup -n observability -o json | jq -r '.items[].status.conditions[0].message'
```
Two possible causes, same symptom:

1. **`folderRef` (name-based lookup) is used instead of `folderUID`.** On the grafana-operator version this repo pins, `folderRef` resolves via the Kubernetes object's `metadata.uid`, which Grafana never uses as the folder's own UID — it always fails. Every alert rule group in `templates/monitors/*.yaml` uses `folderUID` referencing a `GrafanaFolder` with an explicit `spec.uid` pinned (see `templates/monitors/folder.yaml`) specifically to avoid this. Don't revert to `folderRef`.
2. **The folder's `spec.uid` didn't actually take.** `GrafanaFolder.spec.uid` ("Manually specify the UID the Folder is created with") is flaky on create in practice — occasionally the folder lands in Grafana with an auto-generated UID instead of the pinned one, even though the CR looks correct. Verify directly:
   ```bash
   kubectl port-forward svc/grafana 3000:80 -n observability &
   curl -s -u admin:admin http://localhost:3000/api/folders | jq
   ```
   If the `uid` shown doesn't match what `templates/monitors/folder.yaml` pins (`<service>-alerts`), delete both the wrong Grafana-side folder (`DELETE /api/folders/<uid>`) and the `GrafanaFolder` CR, then reapply and re-verify before recreating the alert rule groups. Recreating everything at once tends to hit this race again — do the folder first, confirm its UID, then the rest.

## `found matching Grafana instances ... count: 2` / intermittent `Secret "grafana" not found`

```bash
kubectl get grafana,grafanafolder,grafanadashboard,grafanaalertrulegroup,grafanadatasource -A
```
If anything shows up outside the `observability` namespace, that's the cause. `GrafanaFolder`/`GrafanaDashboard`/`GrafanaAlertRuleGroup`/`GrafanaDatasource`'s `instanceSelector` matches `Grafana` CRs **cluster-wide by label, not by namespace** — a manifest applied without `-n observability` (a stray manual `kubectl apply`, most likely) lands in `default` and grafana-operator tries to reconcile it against every matching instance it finds anywhere, including the real one. Delete the stray resources; always pass `-n observability` on manual applies against this chart's CRDs.

## grafana-operator pod crash-looping: `no matches for kind "Grafana"` / `failed to wait for grafana caches to sync`

```bash
kubectl get crd | grep grafana
```
If `grafanas.grafana.integreatly.org` is missing while the other `grafana.integreatly.org` CRDs are present: the `Grafana` CRD is unusually large (~700KB, full embedded config schema) and exceeds the 262144-byte cap on the `kubectl.kubernetes.io/last-applied-configuration` annotation that client-side apply uses — it fails to apply with no obvious error surfaced through ArgoCD. `deploy/apps/templates/application.yaml` sets `ServerSideApply=true` in `syncOptions` specifically to avoid this (server-side apply doesn't use that annotation). If it recurs (e.g. a new large CRD from a grafana-operator upgrade), apply it directly with `kubectl apply --server-side --force-conflicts -f <crd>.yaml` to unblock, then confirm the sync option is still in place.

## `log-analyzer` stuck in `ImagePullBackOff`

Check which hostname the error references:
```bash
kubectl describe pod -n observability -l app.kubernetes.io/name=log-analyzer | grep -A3 Failed
```
- `dial tcp [::1]:5000: connect: connection refused` (or similar, referencing `localhost:5000`) → the chart's `image.repository` is wrong. k3d's containerd mirror only rewrites the registry's **own** hostname (`k3d-dev-registry:5000`), not `localhost` — that only resolves from the Mac, where `docker push` uses the published port. `deploy/charts/log-analyzer/values.yaml` must use `k3d-dev-registry:5000/...`.
- Image pulls fine but the pod is still running old code after a rebuild → `imagePullPolicy` is `IfNotPresent` and the node already has something cached under the `:dev` tag. It's set to `Always` specifically because `:dev` is a floating tag rebuilt repeatedly in local dev; if it ever gets changed back, `kubectl rollout restart deployment/log-analyzer -n observability` after every rebuild is required to force a fresh pull.

## `POST /runs` returns 422 `Input should be a valid dictionary`

Missing `Content-Type: application/json` on the request — curl defaults to `application/x-www-form-urlencoded` for `-d`, which FastAPI won't parse as the expected dict body. Always include `-H "Content-Type: application/json"`.

## ClickHouse bootstrap Job hangs on "Waiting for ClickHouse service..." forever

The Job's wait loop and the actual bootstrap `clickhouse-client` call both target a hostname — check it's `<cluster.name>-clickhouse-headless`, not bare `<cluster.name>` (`deploy/charts/clickhouse-cluster/templates/bootstrap-job.yaml`). A bare cluster name doesn't resolve to anything; `nslookup`/`getent hosts` from inside a pod confirms which form actually resolves if this is ever in doubt again.

## Helm template renders `0`/wrong values where a threshold/percentage was expected

Check for `| mul <n>` on a float value in any `deploy/charts/*/templates/*.yaml`. Sprig's `mul` does integer multiplication and truncates non-integer operands to `0` first (`0.10 | mul 100` → `0`, not `10`). Use `mulf`/`divf`/`addf` for any float arithmetic in Helm templates.

## General diagnostic order

When something in the observability pipeline looks broken and it's not obvious which layer:
1. `kubectl get pods -n observability` — is everything actually `Running`/`Completed` with 0 unexpected restarts?
2. ClickHouse — does the table have data, and is `min(timestamp)`/`max(timestamp)` sane? (see above)
3. Vector — `kubectl logs -n observability -l app.kubernetes.io/name=vector --tail=100`, look for `WARN`/`ERROR` on the `clickhouse_logs`/`clickhouse_metrics` sinks specifically.
4. Grafana — `kubectl logs -n observability -l app.kubernetes.io/name=grafana --tail=200 | grep -i error`, and/or `./scripts/verify-grafana.sh`.
5. grafana-operator — `kubectl logs -n observability -l app.kubernetes.io/name=grafana-operator --tail=100`, and check every relevant CR's `.status.conditions` directly (`kubectl get grafana<kind> <name> -n observability -o yaml`) rather than trusting `kubectl get`'s summary columns, which can be stale.
