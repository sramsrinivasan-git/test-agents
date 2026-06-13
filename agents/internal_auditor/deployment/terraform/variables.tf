variable "project_id" {
  description = "GCP project that will host the Internal Auditor storage."
  type        = string
}

variable "bq_location" {
  description = "BigQuery dataset location (e.g. US, EU, us-central1)."
  type        = string
  default     = "US"
}

variable "firestore_region" {
  description = "Firestore database location (e.g. nam5, eur3, us-central1)."
  type        = string
  default     = "nam5"
}

variable "bq_dataset_id" {
  description = "BigQuery dataset ID."
  type        = string
  default     = "internal_auditor"
}

variable "firestore_database_id" {
  description = "Firestore named-database ID."
  type        = string
  default     = "internal-auditor-db"
}
