locals {
  kube_context = "k3d-${var.cluster_name}"
}

resource "null_resource" "k3d_cluster" {
  triggers = {
    cluster_name  = var.cluster_name
    registry_name = var.registry_name
    registry_port = tostring(var.registry_port)
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail

      if ! command -v k3d >/dev/null 2>&1; then
        echo "k3d is required. Run scripts/install-tools-macos-arm64.sh first."
        exit 1
      fi

      if ! command -v docker >/dev/null 2>&1; then
        echo "Docker CLI is required. Install/start Docker Desktop first."
        exit 1
      fi

      if ! k3d cluster get ${var.cluster_name} >/dev/null 2>&1; then
        # Create registry first, then cluster using it
        if ! k3d registry get k3d-${var.registry_name} >/dev/null 2>&1; then
          k3d registry create ${var.registry_name} --port ${var.registry_port}
        fi

        k3d cluster create ${var.cluster_name} \
          --servers 1 \
          --agents 0 \
          --wait \
          --registry-use k3d-${var.registry_name}:${var.registry_port} \
          --k3s-arg '--disable=traefik@server:0'
      else
        echo "k3d cluster ${var.cluster_name} already exists"
      fi

      kubectl config use-context ${local.kube_context} >/dev/null
    EOT
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      k3d cluster delete ${self.triggers.cluster_name} >/dev/null 2>&1 || true
      k3d registry delete ${self.triggers.registry_name} >/dev/null 2>&1 || true
    EOT
  }
}

resource "null_resource" "wait_for_cluster" {
  depends_on = [null_resource.k3d_cluster]

  triggers = {
    cluster_name = var.cluster_name
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      export KUBECONFIG=$(eval echo ${var.kubeconfig_path})

      for _ in $(seq 1 60); do
        if kubectl --context ${local.kube_context} get nodes >/dev/null 2>&1; then
          exit 0
        fi
        sleep 2
      done

      echo "Cluster ${local.kube_context} was not ready in time"
      exit 1
    EOT
  }
}

resource "null_resource" "argocd" {
  depends_on = [null_resource.wait_for_cluster]

  triggers = {
    cluster_name       = var.cluster_name
    argocd_namespace   = var.argocd_namespace
    argocd_chart_version = var.argocd_chart_version
  }

  provisioner "local-exec" {
    interpreter = ["/bin/bash", "-c"]
    command     = <<-EOT
      set -euo pipefail
      export KUBECONFIG=$(eval echo ${var.kubeconfig_path})

      kubectl --context ${local.kube_context} create namespace ${var.argocd_namespace} --dry-run=client -o yaml | \
        kubectl --context ${local.kube_context} apply -f -

      helm upgrade --install argocd argo-cd \
        --repo https://argoproj.github.io/argo-helm \
        --version ${var.argocd_chart_version} \
        --namespace ${var.argocd_namespace} \
        --kube-context ${local.kube_context} \
        --set configs.params.server\\.insecure=true \
        --set server.service.type=ClusterIP \
        --set controller.replicas=1 \
        --set repoServer.replicas=1 \
        --set applicationSet.replicas=1 \
        --wait --timeout 5m
    EOT
  }
}
