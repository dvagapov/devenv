#!/usr/bin/env bash
# Verify Grafana actually has a non-empty ClickHouse datasource, dashboards, and
# alert rules — i.e. the grafana-monitoring CRDs (GrafanaDatasource/
# GrafanaDashboard/GrafanaAlertRuleGroup) were picked up by grafana-operator and
# actually landed in Grafana, not just "applied to the cluster".
#
# Usage: ./scripts/verify-grafana.sh
# Env overrides: NAMESPACE, GRAFANA_SVC, GRAFANA_PORT, GRAFANA_USER, GRAFANA_PASSWORD
#
# If Grafana isn't already reachable at $GRAFANA_URL, starts its own
# `kubectl port-forward` and tears it down on exit — doesn't touch one you
# already have running.
set -euo pipefail

NAMESPACE="${NAMESPACE:-observability}"
GRAFANA_SVC="${GRAFANA_SVC:-grafana}"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"
GRAFANA_USER="${GRAFANA_USER:-admin}"
GRAFANA_PASSWORD="${GRAFANA_PASSWORD:-admin}"
BASE_URL="http://localhost:${GRAFANA_PORT}"

PF_PID=""
cleanup() {
  if [ -n "$PF_PID" ]; then
    kill "$PF_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! curl -s -o /dev/null --max-time 1 "${BASE_URL}/api/health"; then
  echo "Grafana not reachable at ${BASE_URL} — starting port-forward to svc/${GRAFANA_SVC} in ns ${NAMESPACE}..." >&2
  kubectl port-forward -n "$NAMESPACE" "svc/${GRAFANA_SVC}" "${GRAFANA_PORT}:80" >/tmp/verify-grafana-portforward.log 2>&1 &
  PF_PID=$!
  ok=0
  for _ in $(seq 1 20); do
    if curl -s -o /dev/null --max-time 1 "${BASE_URL}/api/health"; then
      ok=1
      break
    fi
    sleep 0.5
  done
  if [ "$ok" -ne 1 ]; then
    echo "FAIL: could not reach Grafana via port-forward (see /tmp/verify-grafana-portforward.log)" >&2
    exit 1
  fi
fi

auth=(-u "${GRAFANA_USER}:${GRAFANA_PASSWORD}")
fail=0

echo "== Datasources =="
datasources="$(curl -s "${auth[@]}" "${BASE_URL}/api/datasources")"
echo "$datasources" | jq -r '.[] | "\(.name)\t\(.type)\t\(.uid)"'
ds_count="$(echo "$datasources" | jq 'length')"
echo "count=${ds_count}"
if [ "$ds_count" -eq 0 ]; then
  echo "FAIL: no datasources found (expected the ClickHouse datasource from grafana-monitoring)" >&2
  fail=1
fi
if ! echo "$datasources" | jq -e '.[] | select(.type == "grafana-clickhouse-datasource")' >/dev/null; then
  echo "FAIL: no grafana-clickhouse-datasource datasource found" >&2
  fail=1
fi

echo
echo "== Dashboards =="
dashboards="$(curl -s "${auth[@]}" "${BASE_URL}/api/search?type=dash-db")"
echo "$dashboards" | jq -r '.[] | "\(.title)\t\(.uid)\t\(.folderTitle // "General")"'
dash_count="$(echo "$dashboards" | jq 'length')"
echo "count=${dash_count}"
if [ "$dash_count" -eq 0 ]; then
  echo "FAIL: no dashboards found" >&2
  fail=1
fi

for uid in $(echo "$dashboards" | jq -r '.[].uid'); do
  panels="$(curl -s "${auth[@]}" "${BASE_URL}/api/dashboards/uid/${uid}" | jq '.dashboard.panels | length')"
  echo "  ${uid}: ${panels} panels"
  if [ "$panels" -eq 0 ]; then
    echo "FAIL: dashboard ${uid} has zero panels" >&2
    fail=1
  fi
done

echo
echo "== Alert rules =="
alerts="$(curl -s "${auth[@]}" "${BASE_URL}/api/v1/provisioning/alert-rules")"
echo "$alerts" | jq -r '.[] | "\(.title)\t\(.uid)\t\(.folderUID)"'
alert_count="$(echo "$alerts" | jq 'length')"
echo "count=${alert_count}"
if [ "$alert_count" -eq 0 ]; then
  echo "FAIL: no alert rules found" >&2
  fail=1
fi

echo
if [ "$fail" -eq 0 ]; then
  echo "OK: datasources=${ds_count} dashboards=${dash_count} alert_rules=${alert_count}"
else
  echo "FAILED — see above" >&2
fi
exit "$fail"
