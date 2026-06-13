-- BigQuery DDL for the Internal Auditor agent's compliance ledger.
--
-- Dataset: internal_auditor
-- Tables:  audit_runs, audit_findings, audit_alerts
--
-- How to use:
--   1. Open https://console.cloud.google.com/bigquery
--   2. Confirm the project picker shows your target project.
--   3. Create the dataset first (see DEPLOY.md §1) — this script assumes
--      `internal_auditor` already exists.
--   4. Open a new SQL query tab and paste each CREATE TABLE statement.
--      Run them ONE AT A TIME (the editor runs a single statement per tab).
--
-- Tables are PARTITIONed by their natural time column and CLUSTERed by
-- the most common filter columns, so query cost stays low as the ledger
-- grows. Schemas mirror schemas.py; if you change one, change the other.


-- ─────────────────────────────────────────────────────────────────────
-- Table 1: audit_runs — one row per orchestrator execution
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `internal_auditor.audit_runs` (
  run_id            STRING    NOT NULL  OPTIONS(description = "Unique ID for this audit run (e.g. audit-2026-04-14T10:00:00Z)"),
  trigger_type      STRING    NOT NULL  OPTIONS(description = "scheduled | on_demand (provenance: how the run was kicked off)"),
  trigger_source    STRING              OPTIONS(description = "For scheduled: scheduler job name. For on_demand: caller identifier"),
  started_at        TIMESTAMP NOT NULL  OPTIONS(description = "When the orchestrator began this run"),
  completed_at      TIMESTAMP           OPTIONS(description = "When the orchestrator finished this run"),
  duration_ms       INT64               OPTIONS(description = "Total run duration in milliseconds"),

  window_start      TIMESTAMP           OPTIONS(description = "Lookback window start"),
  window_end        TIMESTAMP           OPTIONS(description = "Lookback window end"),
  lookback_hours    FLOAT64             OPTIONS(description = "Configured lookback interval in hours"),

  verdict           STRING    NOT NULL  OPTIONS(description = "clean | violation | inconclusive"),
  verdict_source    STRING    NOT NULL  OPTIONS(description = "policy_evaluator | ground_truth | human_escalation"),
  total_findings    INT64     NOT NULL  OPTIONS(description = "Number of findings in this run"),
  total_violations  INT64     NOT NULL  OPTIONS(description = "Number of confirmed violations"),
  replan_count      INT64     NOT NULL  OPTIONS(description = "Number of replan loops executed (0-3)"),
  alert_dispatched  BOOL      NOT NULL  OPTIONS(description = "Whether an alert was sent to Pub/Sub"),

  scratchpad_json   JSON                OPTIONS(description = "Full ReAct scratchpad at end of run")
)
PARTITION BY DATE(started_at)
CLUSTER BY trigger_type, verdict
OPTIONS(description = "One row per Internal Auditor orchestrator execution.");


-- ─────────────────────────────────────────────────────────────────────
-- Table 2: audit_findings — one row per finding within a run
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `internal_auditor.audit_findings` (
  finding_id          STRING    NOT NULL  OPTIONS(description = "Unique finding ID"),
  run_id              STRING    NOT NULL  OPTIONS(description = "FK to audit_runs.run_id"),
  trigger_type        STRING    NOT NULL  OPTIONS(description = "scheduled | on_demand (provenance: how the run was kicked off)"),
  found_at            TIMESTAMP NOT NULL  OPTIONS(description = "When this finding was detected"),

  detected_by         STRING    NOT NULL  OPTIONS(description = "log_analyzer | asset_inspector | agent_behavior_evaluator"),

  -- Cloud Logging fields (populated by log_analyzer)
  log_severity        STRING              OPTIONS(description = "Cloud Logging severity: INFO | WARNING | ERROR | CRITICAL"),
  log_method          STRING              OPTIONS(description = "API method (e.g. google.iam.admin.v1.SetIAMPolicy)"),
  log_service         STRING              OPTIONS(description = "GCP service (e.g. iam.googleapis.com)"),
  log_principal       STRING              OPTIONS(description = "Principal email who performed the action"),
  log_resource_name   STRING              OPTIONS(description = "Full resource path from Cloud Logging"),
  log_timestamp       TIMESTAMP           OPTIONS(description = "Original event timestamp from Cloud Logging"),
  log_raw_json        JSON                OPTIONS(description = "Raw Cloud Logging JSON event"),

  -- Cloud Asset fields (populated by asset_inspector)
  asset_type          STRING              OPTIONS(description = "Cloud Asset type (e.g. compute.googleapis.com/Firewall)"),
  asset_name          STRING              OPTIONS(description = "Full asset resource name"),
  asset_project       STRING              OPTIONS(description = "GCP project ID the asset belongs to"),
  asset_iam_role      STRING              OPTIONS(description = "IAM role involved (e.g. roles/owner)"),
  asset_iam_member    STRING              OPTIONS(description = "IAM member (e.g. serviceAccount:sa-deploy@...)"),
  asset_prior_role    STRING              OPTIONS(description = "Previous IAM role (if escalation detected)"),
  asset_snapshot_ts   TIMESTAMP           OPTIONS(description = "Timestamp of the Cloud Asset snapshot"),
  asset_raw_json      JSON                OPTIONS(description = "Raw Cloud Asset export JSON"),

  -- Agent behavior fields (populated by agent_behavior_evaluator)
  agent_id            STRING              OPTIONS(description = "ID of the user-facing agent being monitored"),
  conversation_id     STRING              OPTIONS(description = "Conversation/session ID"),
  agent_user_input    STRING              OPTIONS(description = "What the user asked the agent"),
  agent_response      STRING              OPTIONS(description = "What the agent responded"),
  violation_type      STRING              OPTIONS(description = "hallucination | pii_leak | policy_violation | ungrounded_claim"),
  grounding_sources   JSON                OPTIONS(description = "Grounding sources the agent cited"),

  -- Policy evaluation result (both paths)
  policy_ref          STRING              OPTIONS(description = "GCS path to the governance policy doc matched"),
  policy_clause       STRING              OPTIONS(description = "Specific clause/section of the policy violated"),
  verdict             STRING    NOT NULL  OPTIONS(description = "clean | violation | ambiguous"),
  verdict_source      STRING    NOT NULL  OPTIONS(description = "policy_evaluator | ground_truth:<case_id> | human:<email>"),
  severity            STRING    NOT NULL  OPTIONS(description = "low | medium | high | critical"),
  finding_summary     STRING    NOT NULL  OPTIONS(description = "Human-readable summary of the finding"),

  pattern_key         STRING              OPTIONS(description = "Generalized pattern (e.g. role_grant:roles/editor:staging-*)")
)
PARTITION BY DATE(found_at)
CLUSTER BY run_id, detected_by, verdict
OPTIONS(description = "One row per finding within an Internal Auditor run.");


-- ─────────────────────────────────────────────────────────────────────
-- Table 3: audit_alerts — one row per alert dispatched to Pub/Sub
-- ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `internal_auditor.audit_alerts` (
  alert_id           STRING    NOT NULL  OPTIONS(description = "Unique alert ID"),
  run_id             STRING    NOT NULL  OPTIONS(description = "FK to audit_runs.run_id"),
  finding_id         STRING    NOT NULL  OPTIONS(description = "FK to audit_findings.finding_id"),
  dispatched_at      TIMESTAMP NOT NULL  OPTIONS(description = "When the alert was published to Pub/Sub"),
  pubsub_topic       STRING    NOT NULL  OPTIONS(description = "Pub/Sub topic the alert was published to"),
  pubsub_message_id  STRING              OPTIONS(description = "Pub/Sub message ID returned on publish"),
  severity           STRING    NOT NULL  OPTIONS(description = "low | medium | high | critical"),
  alert_payload      JSON      NOT NULL  OPTIONS(description = "Full JSON payload sent to Pub/Sub"),
  downstream_targets ARRAY<STRING>       OPTIONS(description = "Downstream consumers (e.g. slack, pagerduty, siem)")
)
PARTITION BY DATE(dispatched_at)
CLUSTER BY severity, pubsub_topic
OPTIONS(description = "One row per alert dispatched by the Internal Auditor.");
