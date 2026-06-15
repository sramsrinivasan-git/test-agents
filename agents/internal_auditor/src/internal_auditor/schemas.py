"""Single source of truth for the JSON shapes the agents produce.

The orchestrator + each specialist embed a JSON template into their
instruction prompts so the model knows what to emit. Defining those
templates here (rather than inline in each agent's instruction string)
keeps drift out: change a field name in one place, every agent's
prompt picks it up on the next reload.

Embed them with an f-string in the agent's instruction:

    from internal_auditor import schemas
    INSTRUCTION = f"... Output schema:\n{schemas.LOG_ANALYZER_FINDINGS} ..."
"""

from __future__ import annotations


# Returned by the log_analyzer specialist. `entries` and `total_entries`
# carry the raw MCP-tool response untouched - we don't reshape the audit
# log records here.
LOG_ANALYZER_FINDINGS = """\
{
  "tool_used": "<which MCP tool you called>",
  "window_hours": <number>,
  "filters": { ... what you actually passed ... },
  "total_entries": <int>,
  "entries": [ ... raw entries from the MCP tool, untouched ... ],
  "summary": "<one-paragraph human-readable summary of what you saw>"
}"""


# Returned by the asset_inspector specialist. Anchored at `window_end`
# (a point-in-time snapshot) rather than a duration, because Cloud Asset
# Inventory answers "what does the world look like as of T" rather than
# "what happened between T-window and T".
ASSET_INSPECTOR_FINDINGS = """\
{
  "tool_used": "<which MCP tool you called>",
  "window_end": "<ISO timestamp the snapshot is anchored at>",
  "filters": { ... what you actually passed ... },
  "total_assets": <int>,
  "assets": [ ... raw entries from the MCP tool, untouched ... ],
  "summary": "<one-paragraph human-readable summary of what you saw>"
}"""


# Returned by the orchestrator. `findings.log_analyzer` and
# `findings.asset_inspector` are the verbatim specialist outputs above -
# the orchestrator does not reshape them.
AUDIT_REPORT = """\
{
  "run_id": "<run_id from input>",
  "trigger_type": "<scheduled|on_demand from input, verbatim>",
  "lookback_hours": <float>,
  "findings": {
    "log_analyzer":    <whatever log_analyzer returned, verbatim>,
    "asset_inspector": <whatever asset_inspector returned, verbatim>
  },
  "next_step": "policy_evaluation_pending"
}"""
