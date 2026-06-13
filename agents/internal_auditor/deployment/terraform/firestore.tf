resource "google_firestore_database" "internal_auditor_db" {
  project                 = var.project_id
  name                    = var.firestore_database_id
  location_id             = var.firestore_region
  type                    = "FIRESTORE_NATIVE"
  concurrency_mode        = "OPTIMISTIC"
  app_engine_integration_mode = "DISABLED"

  depends_on = [google_project_service.firestore]
}

# Composite index 1: hot-path lookup of an active precedent by pattern.
#   Query: pattern_key == ? AND verdict == ? AND is_active == true
resource "google_firestore_index" "ground_truth_pattern_lookup" {
  project    = var.project_id
  database   = google_firestore_database.internal_auditor_db.name
  collection = "ground_truth_decisions"
  query_scope = "COLLECTION"

  fields {
    field_path = "pattern_key"
    order      = "ASCENDING"
  }
  fields {
    field_path = "verdict"
    order      = "ASCENDING"
  }
  fields {
    field_path = "is_active"
    order      = "ASCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "ASCENDING"
  }
}

# Composite index 2: TTL/expiry sweep.
#   Query: is_active == true AND expires_at <= now() ORDER BY expires_at
resource "google_firestore_index" "ground_truth_ttl_sweep" {
  project    = var.project_id
  database   = google_firestore_database.internal_auditor_db.name
  collection = "ground_truth_decisions"
  query_scope = "COLLECTION"

  fields {
    field_path = "is_active"
    order      = "ASCENDING"
  }
  fields {
    field_path = "expires_at"
    order      = "ASCENDING"
  }
  fields {
    field_path = "__name__"
    order      = "ASCENDING"
  }
}

# TTL policy: auto-delete docs in ground_truth_decisions ~24h after
# expires_at has passed.
resource "google_firestore_field" "ground_truth_ttl" {
  project    = var.project_id
  database   = google_firestore_database.internal_auditor_db.name
  collection = "ground_truth_decisions"
  field      = "expires_at"

  ttl_config {}
}
