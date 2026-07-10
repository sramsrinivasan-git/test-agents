output "service_name" {
  description = "The name of the Kubernetes service for the agent"
  value       = kubernetes_service.agent_svc.metadata[0].name
}

output "service_endpoint" {
  description = "The internal service endpoint URL for the agent"
  value       = "http://${kubernetes_service.agent_svc.metadata[0].name}.${var.namespace}.svc.cluster.local:80"
}

output "service_account_email" {
  description = "The email of the GCP service account"
  value       = google_service_account.agent_gsa.email
}
