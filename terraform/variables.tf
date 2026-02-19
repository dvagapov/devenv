variable "cluster_name" {
  description = "k3d cluster name"
  type        = string
  default     = "dev"
}

variable "registry_name" {
  description = "Local k3d registry name"
  type        = string
  default     = "dev-registry"
}

variable "registry_port" {
  description = "Local registry host port"
  type        = number
  default     = 5000
}

variable "kubeconfig_path" {
  description = "Path to kubeconfig file"
  type        = string
  default     = "~/.kube/config"
}

variable "argocd_namespace" {
  description = "Namespace for Argo CD"
  type        = string
  default     = "argocd"
}

variable "argocd_chart_version" {
  description = "Argo CD Helm chart version"
  type        = string
  default     = "7.8.2"
}
