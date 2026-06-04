resource "google_bigquery_dataset" "internal_auditor" {
  project       = var.project_id
  dataset_id    = var.bq_dataset_id
  friendly_name = "Internal Auditor"
  description   = "Internal Auditor compliance ledger"
  location      = var.bq_location

  depends_on = [google_project_service.bigquery]
}

resource "google_bigquery_table" "audit_runs" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.internal_auditor.dataset_id
  table_id   = "audit_runs"

  description         = "One row per Internal Auditor orchestrator execution."
  schema              = file("${path.module}/schemas/audit_runs.json")
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "started_at"
  }

  clustering = ["trigger_type", "verdict"]
}

resource "google_bigquery_table" "audit_findings" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.internal_auditor.dataset_id
  table_id   = "audit_findings"

  description         = "One row per finding within an Internal Auditor run."
  schema              = file("${path.module}/schemas/audit_findings.json")
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "found_at"
  }

  clustering = ["run_id", "detected_by", "verdict"]
}

resource "google_bigquery_table" "audit_alerts" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.internal_auditor.dataset_id
  table_id   = "audit_alerts"

  description         = "One row per alert dispatched by the Internal Auditor."
  schema              = file("${path.module}/schemas/audit_alerts.json")
  deletion_protection = true

  time_partitioning {
    type  = "DAY"
    field = "dispatched_at"
  }

  clustering = ["severity", "pubsub_topic"]
}
