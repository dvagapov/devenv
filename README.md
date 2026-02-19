# devenv

Local macOS (ARM64) development environment for Kubernetes with:
- fast local single-node cluster (`k3d`)
- local Docker image registry
- minimal Argo CD install
- per-tool Helm charts (dependencies pulled via `helm dependency update`, upgradable independently)

## Prerequisites

- macOS on Apple Silicon (ARM64)
- Docker Desktop installed and running

## 1) Install / update tools

```bash
chmod +x ./scripts/install-tools-macos-arm64.sh
./scripts/install-tools-macos-arm64.sh
```

Installed tooling: `opentofu`, `kubectl`, `helm`, `k3d`, `argocd`, `jq`, `yq`, `k9s`, `kubectx`.

## 2) Provision local cluster + Argo CD

```bash
cd terraform
tofu init
tofu apply
```

OpenTofu creates:
- `k3d` cluster with 1 server node
- local image registry exposed on `localhost:5000`
- Argo CD in namespace `argocd`

## 3) Push local images to local registry

```bash
docker build -t localhost:5000/my-app:dev .
docker push localhost:5000/my-app:dev
```

## 4) Deploy observability stack via Argo CD

1. Set `argocd.repoURL` in `deployment/apps/values.yaml` to your Git repository.
2. Pull third-party chart dependencies for each tool chart:

```bash
for chart in deployment/charts/*/; do
  helm dependency update "$chart"
done
```

3. Install the apps chart (generates one Argo CD `Application` per entry in values):

```bash
helm upgrade --install argocd-apps deployment/apps -n argocd
```

Add or remove entries from `deployment/apps/values.yaml` to control which apps Argo CD manages.

## Deployment layout

```
deployment/
  apps/                              # Helm chart — generates Argo CD Application CRs
    Chart.yaml
    values.yaml                      # list of applications (name, path, namespace)
    templates/
      application.yaml               # {{range .Values.applications}} loop
  charts/
    kube-state-metrics/              # independent wrapper chart
    metrics-server/
    clickhouse/
    vector/                          # logs + metrics agent → ClickHouse
    grafana/
```

Each tool chart under `charts/` has its own `Chart.yaml` (upstream dependency) and
`values.yaml`, so you can upgrade versions independently.

## Observability components

| Chart dir | Upstream dependency | Purpose |
|---|---|---|
| `kube-state-metrics` | prometheus-community/kube-state-metrics | K8s object-level metrics |
| `metrics-server` | kubernetes-sigs/metrics-server | Node & pod resource metrics |
| `clickhouse` | bitnami/clickhouse | Central data store — ML business data (`ml` DB) + logs & metrics (`observability` DB) |
| `vector` | vector.dev/vector | Lightweight agent — container logs + Prometheus metrics → ClickHouse |
| `grafana` | grafana/grafana | Dashboards with ClickHouse datasource |

## Destroy local environment

```bash
cd terraform
tofu destroy
```
