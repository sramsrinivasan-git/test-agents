terraform {
  required_providers {
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# Local variables for names and paths
locals {
  service_name = "${replace(var.agent_name, "_", "-")}-agent"
  image_name   = "${var.region}-docker.pkg.dev/${var.project_id}/${var.artifact_registry_repo}/${local.service_name}:latest"

  # Generate a unique hash representing all files in the Agent directory and the Dockerfile to trigger rebuilds on changes
  agent_dir_hash = sha1(join("", concat(
    [for f in fileset("${path.module}/../../../agents/${var.agent_name}", "**") : filemd5("${path.module}/../../../agents/${var.agent_name}/${f}")],
    [filemd5("${path.module}/../../../Dockerfile.agent")]
  )))
}

# 1. Build and push the Agent container using serverless Cloud Build
resource "terraform_data" "agent_cloud_build" {
  triggers_replace = {
    dir_sha1 = local.agent_dir_hash
  }

  provisioner "local-exec" {
    command = "gcloud builds submit --config=${path.module}/../../../cloudbuild.yaml --substitutions=_IMAGE_NAME=${local.image_name},_AGENT_NAME=${var.agent_name} ${path.module}/../../../ --project=${var.project_id} --gcs-log-dir=gs://${var.project_id}_cloudbuild/logs"
  }
}

# 2. GCP Service Account for keyless IAM authorization
resource "google_service_account" "agent_gsa" {
  account_id   = "${local.service_name}-sa"
  display_name = "GCP Service Account for GKE Agent: ${local.service_name}"
  project      = var.project_id
}

# 3. Grant keyless Vertex AI access to the GCP service account
resource "google_project_iam_member" "agent_vertex_access" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a. Grant zero-trust Secret Manager read-access so the agent can fetch GITHUB_APP_PRIVATE_KEY in memory
resource "google_project_iam_member" "agent_secret_access" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3. Grant GKE Developer access to deploy container workloads
resource "google_project_iam_member" "agent_gke_developer" {
  project = var.project_id
  role    = "roles/container.developer"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a. Grant GCS Storage Admin access to manage Terraform state files
resource "google_project_iam_member" "agent_storage_admin" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a-2. Grant Compute Viewer access to read GKE node pool metadata
resource "google_project_iam_member" "agent_compute_viewer" {
  project = var.project_id
  role    = "roles/compute.viewer"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a-3. Grant Cloud Build Editor access to trigger MCP server builds
resource "google_project_iam_member" "agent_cloudbuild_editor" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a-4. Grant Service Account User access to act as build service agent
resource "google_project_iam_member" "agent_service_account_user" {
  project = var.project_id
  role    = "roles/iam.serviceAccountUser"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3a-5. Grant Project Viewer access to stream Cloud Build logs
resource "google_project_iam_member" "agent_viewer" {
  project = var.project_id
  role    = "roles/viewer"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 3b. Grant least-privilege BigQuery access for FinOps cost and telemetry analysis
resource "google_project_iam_member" "agent_bigquery_viewer" {
  project = var.project_id
  role    = "roles/bigquery.dataViewer"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

resource "google_project_iam_member" "agent_bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.agent_gsa.email}"
}

# 4. Kubernetes Service Account with Workload Identity annotation
resource "kubernetes_service_account" "agent_ksa" {
  metadata {
    name      = "${local.service_name}-sa"
    namespace = var.namespace
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.agent_gsa.email
    }
  }
}

# 5. Bind Kubernetes service account to GCP service account
resource "google_service_account_iam_member" "workload_identity_binding" {
  service_account_id = google_service_account.agent_gsa.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${var.namespace}/${kubernetes_service_account.agent_ksa.metadata[0].name}]"
}

# 5a. Grant Kubernetes RBAC permissions to create/get/watch/delete SandboxClaims
resource "kubernetes_cluster_role" "agent_sandbox_role" {
  metadata {
    name = "${local.service_name}-sandbox-claimer"
  }
  rule {
    api_groups = ["extensions.agents.x-k8s.io"]
    resources  = ["sandboxclaims"]
    verbs      = ["create", "get", "list", "watch", "update", "patch", "delete"]
  }
}

resource "kubernetes_cluster_role_binding" "agent_sandbox_binding" {
  metadata {
    name = "${local.service_name}-sandbox-binding"
  }
  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = kubernetes_cluster_role.agent_sandbox_role.metadata[0].name
  }
  subject {
    kind      = "ServiceAccount"
    name      = kubernetes_service_account.agent_ksa.metadata[0].name
    namespace = var.namespace
  }
}

# 6. Kubernetes GKE Deployment running the ADK api_server
resource "kubernetes_deployment" "agent_deployment" {
  depends_on = [terraform_data.agent_cloud_build]

  metadata {
    name      = local.service_name
    namespace = var.namespace
    labels = {
      app  = local.service_name
      role = "agent-spoke"
    }
  }

  spec {
    replicas = var.replicas
    selector {
      match_labels = {
        app = local.service_name
      }
    }

    template {
      metadata {
        labels = {
          app  = local.service_name
          role = "agent-spoke"
        }
      }

      spec {
        service_account_name = kubernetes_service_account.agent_ksa.metadata[0].name
        
        container {
          name              = "agent"
          image             = local.image_name
          image_pull_policy = "Always"
          
          # Runs the ADK FastAPI server on port 8080
          command = ["adk", "api_server", "--host", "0.0.0.0", "--port", "8080", "."]

          port {
            container_port = 8080
            name           = "http"
          }

          # Standard Agent Environment Variables
          env {
            name  = "GOOGLE_GENAI_USE_VERTEXAI"
            value = "1"
          }
          env {
            name  = "GOOGLE_CLOUD_LOCATION"
            value = "global"
          }
          env {
            name  = "PRO_MODEL"
            value = var.pro_model
          }
          env {
            name  = "FLASH_MODEL"
            value = var.flash_model
          }
          env {
            name  = "MCP_SERVER_ENDPOINT"
            value = var.mcp_server_endpoint
          }
          env {
            name  = "MCP_TEMPLATE_NAME"
            value = var.mcp_template_name
          }
          env {
            name  = "MCP_NAMESPACE"
            value = var.mcp_namespace
          }
          env {
            name  = "GOOGLE_CLOUD_PROJECT"
            value = var.project_id
          }

          # Custom agent-specific environment variables
          dynamic "env" {
            for_each = var.env_vars
            content {
              name  = env.key
              value = env.value
            }
          }

          resources {
            limits = {
              cpu    = var.cpu_limit
              memory = var.memory_limit
            }
            requests = {
              cpu    = var.cpu_request
              memory = var.memory_request
            }
          }

          #ADK api_server exposes docs route for quick, reliable checks
          liveness_probe {
            http_get {
              path = "/docs"
              port = 8080
            }
            initial_delay_seconds = 15
            period_seconds        = 20
          }

          readiness_probe {
            http_get {
              path = "/docs"
              port = 8080
            }
            initial_delay_seconds = 5
            period_seconds        = 10
          }
        }
      }
    }
  }
}

# 7. Kubernetes Service exposing the Agent internally as a private ClusterIP
resource "kubernetes_service" "agent_svc" {
  metadata {
    name      = "${local.service_name}-svc"
    namespace = var.namespace
    labels = {
      app = local.service_name
    }
    annotations = {
      # Pre-configured hook for Google Identity-Aware Proxy (IAP) / Internal Load Balancer SSO ingress
      "cloud.google.com/backend-config" = "{\"default\": \"agent-iap-config\"}"
    }
  }

  spec {
    type = "ClusterIP"  # Keeps traffic 100% private inside your GKE VPC network
    port {
      port        = 80
      target_port = 8080
      protocol    = "TCP"
      name        = "http"
    }
    selector = {
      app = local.service_name
    }
  }
}
