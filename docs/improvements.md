# Future Improvements

Not required for the current scope — a working list of what's deliberately cut, approximated, or left for later, and why. Ordered roughly by impact.

## Security

- **Secrets are plaintext in Helm values, repeated across charts** (`clickhouse` password, Grafana admin creds). Fine for a disposable local cluster, not fine anywhere real. Next step: External Secrets Operator or Sealed Secrets, one secret per credential, referenced (not duplicated) across `clickhouse-cluster`, `vector`, `grafana`, `grafana-monitoring`.
- **Grafana admin is `admin`/`admin`.** Generate a random password at install time (chart already supports it via a value override) and store it the same way as other secrets above.
- **The ArgoCD repo-credentials secret uses a personal SSH key** (documented as an explicit tradeoff in `docs/local-environment.md`). Replace with a repo-scoped deploy key (read-only) or a fine-grained, short-lived PAT.
- **No TLS between in-cluster components** — Vector→ClickHouse, Grafana→ClickHouse, and the API's own traffic are all plaintext HTTP inside the cluster network. Acceptable for a single-tenant local cluster; not for anything with other workloads sharing the network. Would need cert-manager + mTLS or a service mesh.
- **No NetworkPolicies.** Any pod in the cluster can currently reach ClickHouse, Grafana, and the API. Add default-deny + explicit allow rules per the dependency graph in `docs/observability-rollout.md`.
- **ArgoCD project is `default`** (full cluster access, no RBAC scoping). A real project with restricted `destinations`/`sourceRepos`/`clusterResourceWhitelist` would follow least-privilege.
- **No image scanning.** `log-analyzer`'s image is never scanned for CVEs before deploy — add Trivy/Grype in CI (see below) gating the push to the registry.

## Correctness / architecture

- **Latency is an approximation, not a true percentile.** `http_request_duration_seconds_{sum,count}` gives an *average* over the query window (sum/count), not p95/p99, because Vector's `metric_to_log` + ClickHouse pipeline doesn't currently preserve individual histogram buckets. Fixing this means either (a) ingesting the `_bucket` series too and computing quantiles via interpolation in SQL, or (b) moving latency queries to a backend built for histograms (Mimir/Prometheus) as described in the rollout doc's "storage is pluggable" section — arguably the more correct long-term answer.
- **The availability/synthetic-check monitor reflects requests the process itself received**, not an independent external check — if the pod's network path is fully cut off (not just slow/erroring), this monitor goes quiet (`NoData`) rather than firing "down." A real blackbox prober (external to the pod, e.g. a Vector HTTP check source or blackbox_exporter) would close this gap; scoped out during initial build to avoid new infra (see the "Synthetic check" decision in project history).
- **Single ClickHouse replica, single Grafana replica.** No HA for either. ClickHouse: would need the operator's multi-replica `ClickHouseCluster` support + a real `ClickHouseKeeperCluster` quorum (currently effectively single-node). Grafana: SQLite (even persisted) doesn't support multiple replicas sharing state — would need a Postgres/MySQL backend.
- **No distributed tracing.** Metrics + logs only. Given multiple services calling each other (this repo has one, but the rollout doc assumes hundreds), traces are the piece that actually explains cross-service latency — OTel traces + Tempo would be the natural addition.
- **No real alert routing**, by design (task requirement 4 doesn't ask for it) — see `docs/grafana-guide.md` for how to wire up `GrafanaContactPoint`/`GrafanaNotificationPolicy` CRDs the same declarative way as everything else in `grafana-monitoring` when that's actually needed.

## Operational / CI

- **No CI pipeline.** Nothing currently lints charts, runs `services/log-analyzer`'s test suite, or builds/pushes the image automatically — all done by hand this session. A GitHub Actions workflow doing `helm lint` on every chart + `pytest` + a Trivy scan on PR would catch regressions before they reach a cluster.
- **`:dev` is a floating image tag.** Fine for a single-developer local loop (with `imagePullPolicy: Always`, see `docs/troubleshoot.md`), but there's no way to know which code a running pod actually has without checking the image digest by hand. Tag by git SHA once there's a CI pipeline building images.
- **`terraform/main.tf` is entirely `local-exec` shell provisioners**, not native Terraform/OpenTofu providers — works, but Terraform can't track drift or plan changes to the k3d cluster/ArgoCD install the way it would with e.g. the `helm` provider for the ArgoCD install step. Worth revisiting if this ever needs to run non-interactively in CI rather than a developer's Mac.
- **No automated backup/restore for ClickHouse or Grafana's PVC.** Local dev, so low stakes, but the troubleshooting doc's "Grafana DB wiped" scenario would be a non-event with a backup policy instead of "delete and redeploy the CRDs."

## Code quality / refactoring

- **`services/log-analyzer/src/log_analyzer/api.py` uses the deprecated `@app.on_event("startup")`** (FastAPI warns on every test run) — migrate to a `lifespan` context manager.
- **Request/response bodies are raw `dict`, not Pydantic models.** `POST /runs`' `forceFail`/`forceSlowMs` test-only overrides in particular would benefit from a typed model with validation instead of `body.get(...)` — would also self-document the API better than the README alone.
- **`deploy/charts/grafana-monitoring`'s dashboard JSON is one large inline string in a Helm template**, which makes it hard to lint/validate independently of a full `helm template` render. Extracting panel definitions to standalone `.json.tpl` files (assembled at render time) would make diffs and reviews much easier.
- **The 4 `templates/monitors/*.yaml` files share a lot of structural boilerplate** (instanceSelector, folderUID, resyncPeriod, interval) that's currently copy-pasted per file. A single parameterized template driven by a list of signal definitions in `values.yaml` would remove the duplication — traded off deliberately for "one file per golden signal, easy to read top-to-bottom" per the original request; worth reconsidering if a 5th/6th signal gets added.
- **`docs/troubleshoot.md`'s content overlaps with several "Key facts" bullets in `CLAUDE.md`.** Intentional for now (CLAUDE.md is the terse AI-assistant-facing index, troubleshoot.md is the fuller human-facing runbook) but worth consolidating into one source of truth if they start drifting against each other.

## Features not attempted

- A second example service in `services/` to prove out `grafana-monitoring`'s generic `services:` list against something other than `log-analyzer` (it's designed to generalize — see `deploy/charts/grafana-monitoring/values.yaml` — but only exercised with one service so far).
- Rate limiting / backpressure on `POST /runs` (currently unbounded except by `RUN_MAX_CONCURRENCY`'s effect on the background semaphore — the HTTP endpoint itself never rejects a request).
- OpenAPI/Swagger UI for the Runs API beyond FastAPI's auto-generated `/docs` (never explicitly reviewed/customized).
