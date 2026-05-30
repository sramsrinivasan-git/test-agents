"""
Internal Auditor Agent — Storage Schemas
=========================================
BigQuery  : Compliance ledger (immutable audit trail, analytics, reporting)
Firestore : Ground truth (HITL decisions, low-latency pattern lookup)
Memory Bank : Agent learned intuition (managed by Vertex AI, no schema needed)

Data sources:
  - Cloud Logging API  (JSON audit events)
  - Cloud Asset API    (resource inventory & IAM bindings)
"""


# Here's what's in there:
# BigQuery (4 tables):

# audit_runs — one row per orchestrator execution, captures the full run metadata including trigger type, time window, verdict, replan count, and the complete scratchpad JSON
# audit_findings — one row per finding, with separate field groups for Cloud Logging events (method, principal, resource), Cloud Asset data (asset type, IAM role/member, prior role for escalation detection), and agent behavior violations (hallucination type, conversation ID, grounding sources)
# audit_alerts — one row per Pub/Sub alert dispatched, with the full payload and downstream targets


# Firestore (3 collections):

# ground_truth_decisions — the HITL case law database with pattern matching, TTL-based expiry (90 days default), reuse tracking, and back-references to the BigQuery run that created it
# schema_registry — last known good schemas for Cloud Logging and Cloud Asset API responses, with full revision history so you can see how schemas evolved

# The pattern_key field is the thread that connects BigQuery findings to Firestore ground truth — it's the generalized pattern (like role_grant:roles/editor:staging-*) that makes human decisions reusable across similar future findings.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BIGQUERY SCHEMAS
# Dataset: internal_auditor
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BQ_DATASET = "internal_auditor"

# ──────────────────────────────────────────────────────────────────────────────
# Table 1: audit_runs
# One row per orchestrator execution (batch or realtime trigger)
# ──────────────────────────────────────────────────────────────────────────────
AUDIT_RUNS_TABLE = "audit_runs"
AUDIT_RUNS_SCHEMA = [
    {"name": "run_id",            "type": "STRING",    "mode": "REQUIRED",  "description": "Unique ID for this audit run (e.g. audit-2026-04-14T10:00:00Z)"},
    {"name": "trigger_type",      "type": "STRING",    "mode": "REQUIRED",  "description": "batch | realtime"},
    {"name": "trigger_source",    "type": "STRING",    "mode": "NULLABLE",  "description": "For batch: scheduler job name. For realtime: source agent ID"},
    {"name": "started_at",        "type": "TIMESTAMP", "mode": "REQUIRED",  "description": "When the orchestrator began this run"},
    {"name": "completed_at",      "type": "TIMESTAMP", "mode": "NULLABLE",  "description": "When the orchestrator finished this run"},
    {"name": "duration_ms",       "type": "INTEGER",   "mode": "NULLABLE",  "description": "Total run duration in milliseconds"},

    # Time window (batch path only)
    {"name": "window_start",      "type": "TIMESTAMP", "mode": "NULLABLE",  "description": "Lookback window start (batch only)"},
    {"name": "window_end",        "type": "TIMESTAMP", "mode": "NULLABLE",  "description": "Lookback window end (batch only)"},
    {"name": "lookback_hours",    "type": "FLOAT",     "mode": "NULLABLE",  "description": "Configured lookback interval in hours"},

    # Outcome
    {"name": "verdict",           "type": "STRING",    "mode": "REQUIRED",  "description": "clean | violation | inconclusive"},
    {"name": "verdict_source",    "type": "STRING",    "mode": "REQUIRED",  "description": "policy_evaluator | ground_truth | human_escalation"},
    {"name": "total_findings",    "type": "INTEGER",   "mode": "REQUIRED",  "description": "Number of findings in this run"},
    {"name": "total_violations",  "type": "INTEGER",   "mode": "REQUIRED",  "description": "Number of confirmed violations"},
    {"name": "replan_count",      "type": "INTEGER",   "mode": "REQUIRED",  "description": "Number of replan loops executed (0-3)"},
    {"name": "alert_dispatched",  "type": "BOOLEAN",   "mode": "REQUIRED",  "description": "Whether an alert was sent to Pub/Sub"},

    # Full scratchpad snapshot (for audit trail & human review)
    {"name": "scratchpad_json",   "type": "JSON",      "mode": "NULLABLE",  "description": "Full ReAct scratchpad at end of run"},
]

# ──────────────────────────────────────────────────────────────────────────────
# Table 2: audit_findings
# One row per individual finding within an audit run
# Covers both batch findings (Cloud Logging / Cloud Asset) and
# realtime findings (agent behavior violations)
# ──────────────────────────────────────────────────────────────────────────────
AUDIT_FINDINGS_TABLE = "audit_findings"
AUDIT_FINDINGS_SCHEMA = [
    {"name": "finding_id",        "type": "STRING",    "mode": "REQUIRED",  "description": "Unique finding ID"},
    {"name": "run_id",            "type": "STRING",    "mode": "REQUIRED",  "description": "FK to audit_runs.run_id"},
    {"name": "trigger_type",      "type": "STRING",    "mode": "REQUIRED",  "description": "batch | realtime"},
    {"name": "found_at",          "type": "TIMESTAMP", "mode": "REQUIRED",  "description": "When this finding was detected"},

    # Source agent
    {"name": "detected_by",       "type": "STRING",    "mode": "REQUIRED",  "description": "log_analyzer | asset_inspector | agent_behavior_evaluator"},

    # ── Cloud Logging fields (batch path - log_analyzer) ──
    {"name": "log_severity",      "type": "STRING",    "mode": "NULLABLE",  "description": "Cloud Logging severity: INFO | WARNING | ERROR | CRITICAL"},
    {"name": "log_method",        "type": "STRING",    "mode": "NULLABLE",  "description": "API method (e.g. google.iam.admin.v1.SetIAMPolicy)"},
    {"name": "log_service",       "type": "STRING",    "mode": "NULLABLE",  "description": "GCP service (e.g. iam.googleapis.com, compute.googleapis.com)"},
    {"name": "log_principal",     "type": "STRING",    "mode": "NULLABLE",  "description": "Principal email who performed the action"},
    {"name": "log_resource_name", "type": "STRING",    "mode": "NULLABLE",  "description": "Full resource path from Cloud Logging"},
    {"name": "log_timestamp",     "type": "TIMESTAMP", "mode": "NULLABLE",  "description": "Original event timestamp from Cloud Logging"},
    {"name": "log_raw_json",      "type": "JSON",      "mode": "NULLABLE",  "description": "Raw Cloud Logging JSON event (for traceability)"},

    # ── Cloud Asset fields (batch path - asset_inspector) ──
    {"name": "asset_type",        "type": "STRING",    "mode": "NULLABLE",  "description": "Cloud Asset type (e.g. compute.googleapis.com/Firewall)"},
    {"name": "asset_name",        "type": "STRING",    "mode": "NULLABLE",  "description": "Full asset resource name"},
    {"name": "asset_project",     "type": "STRING",    "mode": "NULLABLE",  "description": "GCP project ID the asset belongs to"},
    {"name": "asset_iam_role",    "type": "STRING",    "mode": "NULLABLE",  "description": "IAM role involved (e.g. roles/owner)"},
    {"name": "asset_iam_member",  "type": "STRING",    "mode": "NULLABLE",  "description": "IAM member (e.g. serviceAccount:sa-deploy@...)"},
    {"name": "asset_prior_role",  "type": "STRING",    "mode": "NULLABLE",  "description": "Previous IAM role (if escalation detected)"},
    {"name": "asset_snapshot_ts", "type": "TIMESTAMP", "mode": "NULLABLE",  "description": "Timestamp of the Cloud Asset snapshot"},
    {"name": "asset_raw_json",    "type": "JSON",      "mode": "NULLABLE",  "description": "Raw Cloud Asset export JSON (for traceability)"},

    # ── Agent behavior fields (realtime path - agent_behavior_evaluator) ──
    {"name": "agent_id",          "type": "STRING",    "mode": "NULLABLE",  "description": "ID of the user-facing agent being monitored"},
    {"name": "conversation_id",   "type": "STRING",    "mode": "NULLABLE",  "description": "Conversation/session ID from the user-facing agent"},
    {"name": "agent_user_input",  "type": "STRING",    "mode": "NULLABLE",  "description": "What the user asked the agent"},
    {"name": "agent_response",    "type": "STRING",    "mode": "NULLABLE",  "description": "What the agent responded"},
    {"name": "violation_type",    "type": "STRING",    "mode": "NULLABLE",  "description": "hallucination | pii_leak | policy_violation | ungrounded_claim"},
    {"name": "grounding_sources", "type": "JSON",      "mode": "NULLABLE",  "description": "Grounding sources the agent cited (or empty if ungrounded)"},

    # ── Policy evaluation result (both paths) ──
    {"name": "policy_ref",        "type": "STRING",    "mode": "NULLABLE",  "description": "GCS path to the governance policy doc that was matched"},
    {"name": "policy_clause",     "type": "STRING",    "mode": "NULLABLE",  "description": "Specific clause/section of the policy that was violated"},
    {"name": "verdict",           "type": "STRING",    "mode": "REQUIRED",  "description": "clean | violation | ambiguous"},
    {"name": "verdict_source",    "type": "STRING",    "mode": "REQUIRED",  "description": "policy_evaluator | ground_truth:<case_id> | human:<email>"},
    {"name": "severity",          "type": "STRING",    "mode": "REQUIRED",  "description": "low | medium | high | critical"},
    {"name": "finding_summary",   "type": "STRING",    "mode": "REQUIRED",  "description": "Human-readable summary of the finding"},

    # ── Pattern key for ground truth matching ──
    {"name": "pattern_key",       "type": "STRING",    "mode": "NULLABLE",  "description": "Generalized pattern (e.g. role_grant:roles/editor:staging-*) for ground truth lookups"},
]

# ──────────────────────────────────────────────────────────────────────────────
# Table 3: audit_alerts
# One row per alert dispatched to Pub/Sub
# ──────────────────────────────────────────────────────────────────────────────
AUDIT_ALERTS_TABLE = "audit_alerts"
AUDIT_ALERTS_SCHEMA = [
    {"name": "alert_id",          "type": "STRING",    "mode": "REQUIRED",  "description": "Unique alert ID"},
    {"name": "run_id",            "type": "STRING",    "mode": "REQUIRED",  "description": "FK to audit_runs.run_id"},
    {"name": "finding_id",        "type": "STRING",    "mode": "REQUIRED",  "description": "FK to audit_findings.finding_id"},
    {"name": "dispatched_at",     "type": "TIMESTAMP", "mode": "REQUIRED",  "description": "When the alert was published to Pub/Sub"},
    {"name": "pubsub_topic",      "type": "STRING",    "mode": "REQUIRED",  "description": "Pub/Sub topic the alert was published to"},
    {"name": "pubsub_message_id", "type": "STRING",    "mode": "NULLABLE",  "description": "Pub/Sub message ID returned on publish"},
    {"name": "severity",          "type": "STRING",    "mode": "REQUIRED",  "description": "low | medium | high | critical"},
    {"name": "alert_payload",     "type": "JSON",      "mode": "REQUIRED",  "description": "Full JSON payload sent to Pub/Sub"},
    {"name": "downstream_targets","type": "STRING",    "mode": "REPEATED",  "description": "Downstream consumers (e.g. slack, pagerduty, siem)"},
]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FIRESTORE SCHEMAS
# Database: internal-auditor-db
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FIRESTORE_DB = "internal-auditor-db"

# ──────────────────────────────────────────────────────────────────────────────
# Collection 1: ground_truth_decisions
# Human-verified precedents for the HITL feedback loop
# Path: ground_truth_decisions/{case_id}
#
# Indexed on: pattern_key, verdict, decided_at (for TTL expiry queries)
# ──────────────────────────────────────────────────────────────────────────────
GROUND_TRUTH_COLLECTION = "ground_truth_decisions"
GROUND_TRUTH_DOC_SCHEMA = {
    "case_id":        "string  (auto-generated, e.g. gt-001)",
    "pattern_key":    "string  (generalized pattern for matching, e.g. role_grant:roles/editor:staging-*)",
    "pattern_type":   "string  (iam_role_grant | firewall_change | asset_config_drift | agent_hallucination | agent_pii_leak)",

    # What was the finding?
    "finding_summary":"string  (human-readable description of the original finding)",
    "original_finding": {
        "detected_by":   "string  (log_analyzer | asset_inspector | agent_behavior_evaluator)",
        "log_method":    "string  (e.g. SetIAMPolicy) — nullable",
        "asset_type":    "string  (e.g. compute.googleapis.com/Firewall) — nullable",
        "resource_path": "string  (e.g. projects/prod-project-01/...) — nullable",
        "agent_id":      "string  (source agent ID for realtime path) — nullable",
    },

    # Human decision
    "verdict":        "string  (not_violation | violation | escalate_always)",
    "reasoning":      "string  (human's explanation of why this verdict)",
    "decided_by":     "string  (email of the human who made the decision)",
    "decided_at":     "timestamp",

    # Lifecycle
    "ttl_days":       "integer (expiry in days, default 90 — after which precedent becomes soft match)",
    "expires_at":     "timestamp (decided_at + ttl_days — for TTL queries)",
    "is_active":      "boolean (false if manually invalidated by a human)",
    "times_reused":   "integer (incremented each time the agent applies this precedent)",
    "last_reused_at": "timestamp (last time this precedent was applied)",

    # Audit trail
    "created_from_run_id":    "string  (FK to BigQuery audit_runs.run_id)",
    "created_from_finding_id":"string  (FK to BigQuery audit_findings.finding_id)",
}

# ──────────────────────────────────────────────────────────────────────────────
# Collection 2: schema_registry
# Last known good schemas for Cloud Logging and Cloud Asset API responses
# Used by Log Analyzer and Asset Inspector for drift detection
# Path: schema_registry/{source_api}/{event_type}
#
# Example doc path: schema_registry/cloud_logging/iam_setiampolicy
# ──────────────────────────────────────────────────────────────────────────────
SCHEMA_REGISTRY_COLLECTION = "schema_registry"
SCHEMA_REGISTRY_DOC_SCHEMA = {
    "source_api":     "string  (cloud_logging | cloud_asset)",
    "event_type":     "string  (e.g. iam_setiampolicy, compute_firewalls_patch)",
    "last_updated":   "timestamp (when this schema was last confirmed valid)",
    "updated_by_run": "string  (run_id that last validated this schema)",

    # The actual schema
    "expected_fields": [
        {
            "field_name": "string  (e.g. principalEmail)",
            "field_type": "string  (string | integer | boolean | object | array)",
            "path":       "string  (dot-notation path, e.g. protoPayload.authenticationInfo.principalEmail)",
            "required":   "boolean",
        }
    ],

    # History of changes
    "revision_history": [
        {
            "changed_at":    "timestamp",
            "change_type":   "string  (field_added | field_removed | field_renamed | type_changed)",
            "old_field":     "string  (nullable)",
            "new_field":     "string  (nullable)",
            "detected_in_run":"string (run_id)",
        }
    ],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QUICK REFERENCE: WHICH STORE FOR WHAT
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#
# ┌──────────────────────────┬──────────────┬──────────────────────────────────┐
# │ Data                     │ Store        │ Why                              │
# ├──────────────────────────┼──────────────┼──────────────────────────────────┤
# │ Full audit run records   │ BigQuery     │ Immutable compliance ledger      │
# │ Individual findings      │ BigQuery     │ Queryable for dashboards/reports │
# │ Alert dispatch history   │ BigQuery     │ Proof alerts were sent           │
# │ Human decisions (HITL)   │ Firestore    │ Sub-ms exact-match lookups       │
# │ API schema registry      │ Firestore    │ Low-latency drift comparison     │
# │ Agent learned patterns   │ Memory Bank  │ Semantic cross-session knowledge │
# │ Soft intuition/context   │ Memory Bank  │ LLM-extracted from experience    │
# └──────────────────────────┴──────────────┴──────────────────────────────────┘

