# Internal Auditor Agent — Project Plan

## Overview

This is a **POC** for a dual-mode GCP compliance auditing agent built on Vertex AI Agent Engine (Gemini). The agent continuously monitors GCP infrastructure and user-facing AI agents for security violations and policy breaches.

Two operational modes:

- **Batch mode** — runs on a configurable cadence (30m / 1h / 6h / 12h) to detect infrastructure drift by checking Cloud Logging audit events and Cloud Asset API resource configurations against organizational governance policies stored in GCS.
- **Real-time mode** — subscribes to the live exhaust of user-facing AI agents (support bots, advisors, etc.) via Pub/Sub and evaluates each conversation turn for hallucinations, PII leaks, ungrounded claims, and policy violations within seconds.

Both paths converge on the same policy evaluation and alerting pipeline. The orchestrator maintains a ReAct-style scratchpad to enable intelligent replanning without infinite loops.

---

## Architecture decisions and rationale

These are decisions made during the design phase. They are final — do not revisit or re-architect these without explicit instruction.

### 1. Orchestrator is an explicit parent agent

The Orchestrator Agent is the root agent that coordinates all sub-agents. It receives triggers, decides which sub-agents to invoke based on `trigger_type`, merges findings from parallel sub-agents, and makes the final violation/clean/escalation decision. Without it, the sub-agents would be a disconnected pipeline, not an agentic system. The orchestrator is what enables reasoning, conditional branching, and replanning.

### 2. Dual-trigger architecture (batch + real-time)

A scheduled batch job is appropriate for infrastructure drift detection (Cloud Asset API checks) because infrastructure changes infrequently. However, monitoring user-facing AI agents in real-time requires immediate evaluation — waiting an hour to catch a hallucination is too slow. Both triggers feed the same Orchestrator Agent with different `trigger_type` values, and the orchestrator routes to different sub-agents accordingly.

### 3. Simple scheduling — Cloud Scheduler + Cloud Function

No Firestore config database, no admin UI. This is a POC. Cloud Scheduler fires a cron job, a Cloud Function computes the lookback window from an environment variable (`LOOKBACK_HOURS`), and calls the Orchestrator. To change the interval, manually update the cron expression and env var in Cloud Console. Two `gcloud` commands.

### 4. Cloud Functions are thin triggers, NOT middleware

The Cloud Functions do NOT parse API responses, transform JSON, or do data processing. The batch CF sends `{ trigger_type: "batch", lookback_hours: 1 }`. The real-time CF forwards the raw Pub/Sub event as `{ trigger_type: "realtime", raw_event: <event> }`. This was a deliberate decision after reviewing peer feedback that CFs are brittle — in our design they are not, because they don't touch API data. The agents themselves handle all data interpretation via LLM reasoning.

### 5. Schema drift detection lives inside agents, not at the CF layer

The Log Analyzer and Asset Inspector agents compare incoming API responses against a last known good schema (stored in Firestore `schema_registry` collection) before processing. If drift is detected (new fields, renamed fields, missing fields), the agent reasons about how to map the new structure to its internal canonical format. This makes the pipeline self-healing when GCP APIs evolve.

### 6. ReAct scratchpad prevents infinite replan loops

The Orchestrator maintains a JSON scratchpad in its session state throughout each audit run. Before every action, it reads the scratchpad to see what was already tried. Before every replan, it checks that the proposed query is different from all previous `steps_taken`. Three guardrails enforce this:
- Max replan count: 3
- Query deduplication against `steps_taken`
- Each replan must target a specific `open_questions` item

If all 3 replans are exhausted, the run terminates as "inconclusive" and escalates to a human reviewer with the full scratchpad attached.

### 7. HITL ground truth memory (case law pattern)

Before the orchestrator escalates an ambiguous finding to a human, it queries the Firestore `ground_truth_decisions` collection for prior human rulings on similar patterns. If a match is found (e.g., a human previously ruled that `role_grant:roles/editor:staging-*` is not a violation), the agent overwrites its scratchpad verdict with the human-verified correction and continues the flow — no escalation needed. When a human does review a new case, their decision is stored as a reusable precedent with a 90-day TTL. This prevents the agent from repeatedly escalating the same type of finding.

### 8. Three storage layers (all three are required)

- **BigQuery** — immutable compliance ledger. Every audit run, finding, and alert is recorded permanently for regulatory compliance, dashboards, and trend analysis. This is the core deliverable.
- **Firestore** — operational ground truth and schema registry. Sub-millisecond exact-match lookups for HITL decisions and schema drift comparison. Not for analytics.
- **Memory Bank** (Vertex AI Agent Engine) — agent's learned semantic intuition. Extracts and remembers soft patterns across sessions (e.g., "staging environments tend to be low-risk", "Cloud Logging renamed this field last month"). No explicit schema — managed by Vertex AI.

### 9. Two separate MCP servers (not one combined)

Cloud Logging and Cloud Asset API are exposed as two separate MCP servers, not one combined server. Reasons:
- **Fault isolation** — if Cloud Asset API hits quota, the Cloud Logging MCP server still works
- **Independent scaling** — real-time path never touches Cloud Asset or Cloud Logging tools
- **Auth scope isolation** — each server runs with least-privilege IAM permissions

---

## Agents

| Agent | Role | Parent | Trigger path |
|---|---|---|---|
| Orchestrator Agent | Receives triggers, coordinates sub-agents, maintains scratchpad, makes violation decisions, can replan up to 3 times | None (root) | Both |
| Log Analyzer Agent | Queries Cloud Logging API for audit events within the lookback window | Orchestrator | Batch |
| Asset Inspector Agent | Exports resource state snapshot at window_end via Cloud Asset API | Orchestrator | Batch |
| Agent Behavior Evaluator | Evaluates a single conversation turn from a user-facing agent for hallucination, grounding failures, PII leaks, and policy violations | Orchestrator | Real-time |
| Policy Evaluator Agent | Cross-references findings against governance policy documents in GCS via RAG (Vertex AI Search) | Orchestrator | Both |
| Alert Dispatcher Agent | Composes structured breach alert payload and publishes to Pub/Sub | Orchestrator | Both |

---

## Agent intents

| Intent | Owner | Description |
|---|---|---|
| `run_scheduled_audit` | Orchestrator | Entry point for batch path — receives time window payload, initializes empty scratchpad |
| `evaluate_agent_event` | Orchestrator | Entry point for real-time path — receives a single agent conversation turn, initializes scratchpad |
| `determine_audit_scope` | Orchestrator | Reads trigger_type and decides which sub-agents to invoke (batch → Log Analyzer + Asset Inspector in parallel; real-time → Agent Behavior Evaluator) |
| `manage_scratchpad` | Orchestrator | Reads and appends to execution state scratchpad before every decision |
| `check_precedent` | Orchestrator | Queries Firestore ground_truth_decisions for prior human rulings matching current finding pattern — called after ambiguous verdict, before escalation |
| `check_audit_logs` | Log Analyzer | Pulls JSON audit events from Cloud Logging API filtered by time window |
| `export_resource_state` | Asset Inspector | Exports GCP resource state via Cloud Asset API, snapshot at window_end |
| `evaluate_agent_response` | Agent Behavior Evaluator | Checks a single agent response for hallucination, PII leakage, and policy compliance |
| `evaluate_policy_compliance` | Policy Evaluator | Compares merged findings against governance documents in GCS via RAG |
| `replan_audit` | Orchestrator | Reads scratchpad, formulates a different query from all previous steps_taken, increments replan_count (max 3) |
| `trigger_breach_alert` | Alert Dispatcher | Composes JSON alert payload and publishes to Pub/Sub breach alert topic |
| `log_clean_result` | Orchestrator | Writes "no violation found" result to BigQuery |
| `escalate_to_human` | Orchestrator | Fires when replan_count reaches max (3) AND ground truth returns a miss — logs as "inconclusive" with full scratchpad |

---

## Tools

### MCP Server 1: Cloud Logging

Used by: Log Analyzer Agent

| Tool | Description |
|---|---|
| `query_audit_logs` | Pulls audit log entries filtered by time window, service, method, and principal |
| `get_log_entry` | Fetches a single log entry by insert ID (for replan deep dives) |
| `list_log_sinks` | Discovers configured log sinks and their destinations |

### MCP Server 2: Cloud Asset

Used by: Asset Inspector Agent

| Tool | Description |
|---|---|
| `search_all_resources` | Searches resource inventory by type, project, or name pattern |
| `search_all_iam_policies` | Searches IAM bindings across the org by role, member, or resource |
| `get_asset_history` | Returns change history for a specific resource (for the replan "what was the prior role?" query) |

### Other tools (direct API calls, not MCP)

| Tool | Used by | Description |
|---|---|---|
| Cloud Storage (GCS) API | Policy Evaluator | Read governance policy documents |
| Vertex AI Search | Policy Evaluator | RAG grounding layer — indexes GCS policy docs for semantic retrieval |
| Pub/Sub API | Alert Dispatcher | Publish breach alerts to alert topic |
| BigQuery API | Orchestrator | Write audit results (violations, clean, inconclusive) with full scratchpad |
| Firestore API | Orchestrator | Query/write ground_truth_decisions; read/update schema_registry |

---

## Infrastructure (outside the agent)

| Component | Role | Configuration |
|---|---|---|
| Cloud Scheduler | Fires on configurable cadence to trigger batch audit runs | Cron expression set manually (e.g., `0 * * * *` for hourly) |
| Cloud Function (batch trigger) | Computes lookback window and calls Orchestrator | Env var `LOOKBACK_HOURS=1`. Computes `window_start = now() - LOOKBACK_HOURS`, `window_end = now()` |
| Cloud Function (real-time trigger) | Subscribes to agent exhaust Pub/Sub topic, forwards raw event to Orchestrator | Triggered by Pub/Sub push subscription. Passes `trigger_type: "realtime"` |
| Pub/Sub (agent exhaust topic) | Receives real-time conversation turns from all user-facing agents | User-facing agents publish every conversation turn here |
| Pub/Sub (breach alert topic) | Receives alerts from Alert Dispatcher | Downstream subscribers: Slack, PagerDuty, SIEM |
| BigQuery (audit log sink) | Continuous log sink from Cloud Logging | For long-term compliance history, separate from agent-written audit results |
| GCS (governance policies bucket) | Stores organizational governance policy documents | Periodically batch-ingested. Indexed by Vertex AI Search for RAG |

---

## Storage schemas

The full schema definitions are in `auditor-agent-schemas.py`. Summary below.

### BigQuery — dataset: `internal_auditor`

**Table: `audit_runs`** — one row per orchestrator execution (batch or realtime trigger). Fields include: run_id, trigger_type, trigger_source, started_at, completed_at, duration_ms, window_start/end (batch only), lookback_hours, verdict (clean | violation | inconclusive), verdict_source (policy_evaluator | ground_truth | human_escalation), total_findings, total_violations, replan_count, alert_dispatched, scratchpad_json (full ReAct scratchpad at end of run).

**Table: `audit_findings`** — one row per individual finding. Has separate field groups for:
- Cloud Logging fields (log_severity, log_method, log_service, log_principal, log_resource_name, log_timestamp, log_raw_json)
- Cloud Asset fields (asset_type, asset_name, asset_project, asset_iam_role, asset_iam_member, asset_prior_role, asset_snapshot_ts, asset_raw_json)
- Agent behavior fields (agent_id, conversation_id, agent_user_input, agent_response, violation_type, grounding_sources)
- Policy evaluation result (policy_ref, policy_clause, verdict, verdict_source, severity, finding_summary)
- Pattern key for ground truth matching (pattern_key)

**Table: `audit_alerts`** — one row per alert dispatched to Pub/Sub. Fields include: alert_id, run_id, finding_id, dispatched_at, pubsub_topic, pubsub_message_id, severity, alert_payload (full JSON), downstream_targets (repeated string).

### Firestore — database: `internal-auditor-db`

**Collection: `ground_truth_decisions`** — path: `ground_truth_decisions/{case_id}`. Human-verified precedents for the HITL feedback loop. Indexed on pattern_key, verdict, decided_at. Key fields: case_id, pattern_key, pattern_type, finding_summary, original_finding (nested: detected_by, log_method, asset_type, resource_path, agent_id), verdict (not_violation | violation | escalate_always), reasoning, decided_by, decided_at, ttl_days (default 90), expires_at, is_active, times_reused, last_reused_at, created_from_run_id, created_from_finding_id.

**Collection: `schema_registry`** — path: `schema_registry/{source_api}/{event_type}`. Last known good schemas for Cloud Logging and Cloud Asset API responses. Key fields: source_api, event_type, last_updated, updated_by_run, expected_fields (array of {field_name, field_type, path, required}), revision_history (array of {changed_at, change_type, old_field, new_field, detected_in_run}).

### Memory Bank (Vertex AI Agent Engine)

No explicit schema. Managed by Vertex AI. The agent's learned semantic intuition is automatically extracted from conversation sessions. Used for soft pattern recognition like "staging environments tend to be low-risk" or "Cloud Logging changed its IAM event schema 2 weeks ago."

---

## Scratchpad schema (ReAct execution state)

The Orchestrator maintains this JSON object in session state throughout each audit run:

```json
{
  "run_id": "audit-<timestamp>",
  "trigger_type": "batch | realtime",
  "steps_taken": [
    {
      "step": 1,
      "agent": "log_analyzer | asset_inspector | policy_evaluator | agent_behavior_evaluator",
      "query": "description of what was asked",
      "result_summary": "what came back",
      "status": "complete | needs_more_context"
    }
  ],
  "findings_so_far": ["list of findings discovered so far"],
  "open_questions": ["unresolved questions that need more data"],
  "replan_count": 0,
  "replan_reason": "why the agent is replanning (null if not replanning)",
  "verdict": "clean | violation | inconclusive | null",
  "verdict_source": "policy_evaluator | ground_truth:<case_id> | human:<email> | null",
  "alert_dispatched": false
}
```

Guardrails:
- Max replan count: 3
- Query deduplication: before each action, check steps_taken — proposed query must differ from all previous queries
- Open question targeting: each replan must target a specific item in open_questions
- If replans exhausted: terminate as "inconclusive", escalate to human with full scratchpad

---

## Sample flows

### Batch path

1. Cloud Scheduler fires at configured cadence (e.g., every 1 hour).
2. Cloud Function (batch) computes `window_start = now() - 1h`, `window_end = now()` → calls Orchestrator with `{ trigger_type: "batch", window_start, window_end }`.
3. Orchestrator initializes empty scratchpad, reads `trigger_type: "batch"`, invokes Log Analyzer and Asset Inspector in parallel.
4. Log Analyzer calls Cloud Logging API with `timestamp >= window_start AND timestamp < window_end` → returns IAM events (e.g., "sa-deploy@ granted roles/owner at T-35min").
5. Asset Inspector calls Cloud Asset API → returns resource snapshot (e.g., "sa-deploy@ currently holds roles/owner on prod-project-01").
6. Orchestrator appends both results to scratchpad, merges findings, passes combined context to Policy Evaluator.
7. Policy Evaluator RAGs against governance docs in GCS → returns verdict.
8. If **ambiguous**: Orchestrator queries Firestore ground_truth_decisions for matching pattern.
   - Ground truth **hit**: overwrite scratchpad verdict with human-verified correction, continue flow.
   - Ground truth **miss**: increment replan_count, refine query based on open_questions, loop back to step 4 with different query.
   - Replan count **maxed (3)**: escalate to human with full scratchpad.
9. If **violation**: invoke Alert Dispatcher → publish to Pub/Sub → Slack/SIEM receive notification.
10. If **clean**: log clean result.
11. Full scratchpad and audit result written to BigQuery.

### Real-time path

1. User-facing support chatbot responds to a customer with potentially incorrect information.
2. Chatbot publishes conversation turn to Pub/Sub agent exhaust topic: `{ agent_id, user_input, agent_response, grounding_sources }`.
3. Cloud Function (real-time) receives event → calls Orchestrator with `{ trigger_type: "realtime", raw_event: <event> }`.
4. Orchestrator initializes scratchpad, reads `trigger_type: "realtime"`, invokes Agent Behavior Evaluator.
5. Agent Behavior Evaluator checks: grounding quality, PII exposure, policy compliance of the response.
6. Orchestrator passes findings to Policy Evaluator → RAGs against governance docs → returns verdict.
7. Same decision flow as batch path (ground truth check → replan or escalate → alert or log clean).
8. Full scratchpad and audit result written to BigQuery.

---

## Build order (suggested)

### Phase 1: Storage layer
- [ ] Create BigQuery dataset `internal_auditor` with tables: `audit_runs`, `audit_findings`, `audit_alerts`
- [ ] Create Firestore database `internal-auditor-db` with collections: `ground_truth_decisions`, `schema_registry`
- [ ] Seed `schema_registry` with initial expected schemas for Cloud Logging IAM events and Cloud Asset IAM bindings

### Phase 2: MCP servers
- [ ] Build MCP Server 1 (Cloud Logging) with tools: `query_audit_logs`, `get_log_entry`, `list_log_sinks`
- [ ] Build MCP Server 2 (Cloud Asset) with tools: `search_all_resources`, `search_all_iam_policies`, `get_asset_history`
- [ ] Each server uses its own service account with least-privilege IAM permissions

### Phase 3: Sub-agents
- [ ] Build Log Analyzer Agent — uses Cloud Logging MCP server, includes schema drift detection against Firestore schema_registry
- [ ] Build Asset Inspector Agent — uses Cloud Asset MCP server, includes schema drift detection
- [ ] Build Agent Behavior Evaluator — evaluates conversation turns for hallucination, PII, grounding, policy compliance
- [ ] Build Policy Evaluator Agent — RAGs against GCS governance docs via Vertex AI Search
- [ ] Build Alert Dispatcher Agent — composes and publishes Pub/Sub alerts

### Phase 4: Orchestrator
- [ ] Build Orchestrator Agent with ReAct scratchpad, routing logic, parallel invocation, replan loop, ground truth lookup
- [ ] Implement scratchpad guardrails (max 3 replans, query deduplication, open question targeting)
- [ ] Implement ground truth query/store flow with Firestore
- [ ] Implement BigQuery write for all audit results

### Phase 5: Trigger layer
- [ ] Deploy Cloud Function (batch trigger) with `LOOKBACK_HOURS` env var
- [ ] Deploy Cloud Function (real-time trigger) with Pub/Sub push subscription
- [ ] Create Cloud Scheduler job with configurable cron expression
- [ ] Create Pub/Sub topics: agent exhaust topic, breach alert topic

### Phase 6: Integration and testing
- [ ] End-to-end batch path test with real Cloud Logging data
- [ ] End-to-end real-time path test with simulated agent exhaust events
- [ ] Test replan loop with ambiguous finding that requires refined query
- [ ] Test ground truth hit/miss paths
- [ ] Test schema drift detection with modified API response structure
- [ ] Verify all results written to BigQuery correctly

---

## Key files

| File | Purpose |
|---|---|
| `auditor-agent-schemas.py` | BigQuery and Firestore schema definitions (source of truth) |
| `plan.md` | This file — project plan and architecture context |

---

## GCP services used

- Vertex AI Agent Engine (Gemini) — LLM backbone and agent runtime
- Vertex AI Search — RAG grounding for governance policy documents
- Vertex AI Memory Bank — cross-session semantic memory
- Cloud Logging API — audit event source
- Cloud Asset API — resource inventory and IAM binding source
- Cloud Storage (GCS) — governance policy document storage
- BigQuery — compliance audit trail (immutable ledger)
- Firestore — ground truth decisions + schema registry (low-latency operational store)
- Pub/Sub — agent exhaust ingestion + breach alert dispatch
- Cloud Scheduler — batch trigger cadence
- Cloud Functions — thin trigger handlers (batch + real-time)
