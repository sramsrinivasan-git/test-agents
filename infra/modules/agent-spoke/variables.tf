variable "agent_name" {
  type        = string
  description = "The name of the cognitive agent (e.g., synthetic_data, adversarial_testing)"
}

variable "project_id" {
  type        = string
  description = "The GCP Project ID"
}

variable "region" {
  type        = string
  description = "The GCP region"
  default     = "us-central1"
}

variable "artifact_registry_repo" {
  type        = string
  description = "The Artifact Registry repository name"
  default     = "aaas-repo"
}

variable "namespace" {
  type        = string
  description = "The Kubernetes namespace to deploy the agent pod into"
  default     = "default"
}

variable "replicas" {
  type        = number
  description = "Number of pod replicas"
  default     = 1
}

variable "cpu_request" {
  type        = string
  description = "CPU request for the pod"
  default     = "100m"
}

variable "cpu_limit" {
  type        = string
  description = "CPU limit for the pod"
  default     = "500m"
}

variable "memory_request" {
  type        = string
  description = "Memory request for the pod"
  default     = "256Mi"
}

variable "memory_limit" {
  type        = string
  description = "Memory limit for the pod"
  default     = "512Mi"
}

# MCP wiring (which warm pools / templates / namespace an agent uses) is
# agent-specific and passed through `env_vars`, not baked into the module —
# agents vary from zero to several MCP servers, so there is no single
# "the MCP server" for a generic agent spoke.

variable "pro_model" {
  type        = string
  description = "The Gemini Pro model to use"
  default     = "gemini-pro-latest"
}

variable "flash_model" {
  type        = string
  description = "The Gemini Flash model to use"
  default     = "gemini-flash-latest"
}

variable "env_vars" {
  type        = map(string)
  description = "Extra environment variables to pass to the agent container"
  default     = {}
}
