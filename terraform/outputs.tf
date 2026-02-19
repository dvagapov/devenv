output "kube_context" {
  description = "kubectl context for the local cluster"
  value       = local.kube_context
}

output "local_registry" {
  description = "Local Docker registry endpoint for pushes"
  value       = "localhost:${var.registry_port}"
}

output "argocd_namespace" {
  value = var.argocd_namespace
}
