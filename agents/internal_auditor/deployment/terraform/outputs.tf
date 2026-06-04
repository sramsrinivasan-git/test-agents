output "bq_dataset_id" {
  description = "Fully-qualified BigQuery dataset ID."
  value       = "${var.project_id}:${google_bigquery_dataset.internal_auditor.dataset_id}"
}

output "bq_tables" {
  description = "BigQuery table IDs created."
  value = [
    google_bigquery_table.audit_runs.table_id,
    google_bigquery_table.audit_findings.table_id,
    google_bigquery_table.audit_alerts.table_id,
  ]
}

output "firestore_database" {
  description = "Firestore database name."
  value       = google_firestore_database.internal_auditor_db.name
}
