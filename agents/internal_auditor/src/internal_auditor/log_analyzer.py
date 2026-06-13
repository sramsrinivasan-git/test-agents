"""Log Analyzer sub-agent.

Pulls Cloud Logging audit events for the time window the orchestrator
passes, via the gcp-log-analyzer MCP server already deployed in the
cluster. Returns structured findings.

Explicitly does NOT classify any entry as a violation - that's the
future Policy Agent's job per plan.md.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPServerParams,
)

from internal_auditor.config import GCP_LOG_ANALYZER_MCP_URL, GEMINI_MODEL

# Connection to the in-cluster MCP server. ADK opens the streamable-http
# session lazily on first tool call and reuses it across the agent run.
log_analyzer_mcp = MCPToolset(
    connection_params=StreamableHTTPServerParams(url=GCP_LOG_ANALYZER_MCP_URL),
)


LOG_ANALYZER_INSTRUCTION = """\
You are the Log Analyzer agent inside the Internal Auditor.

Goal: given a time window (and optional filters like resource_type,
service, principal, severity), call the gcp-log-analyzer MCP tools to
fetch the audit log entries that fall inside that window. Return what
you found - nothing more.

Tool selection:
- `recent_errors`        - first reach when the question is "anything
                           broken in the last N hours?".
- `query_logs`           - when the orchestrator specifies an explicit
                           Cloud Logging filter (severity, resource type,
                           method, principal, log name, etc.).
- `summarize_errors`     - bucket findings by resource_type / log_name /
                           severity for a triage rollup.
- `top_error_messages`   - dedupe a noisy stream into the loudest
                           messages.
- `severity_histogram`   - quick health snapshot of a project / resource.
- `list_log_names`       - exploratory only; when the orchestrator
                           doesn't know what logs exist.

Output (JSON, single object - this is your final response):
{
  "tool_used": "<which MCP tool you called>",
  "window_hours": <number>,
  "filters": { ... what you actually passed ... },
  "total_entries": <int>,
  "entries": [ ... raw entries from the MCP tool, untouched ... ],
  "summary": "<one-paragraph human-readable summary of what you saw>"
}

CRITICAL constraints:
- Do NOT label any entry as a violation, suspicious, anomalous, etc. You
  report; the Policy Agent (added later) decides.
- Do NOT invent fields the MCP tool didn't return.
- If the tool returns zero entries, that's a valid result - say so.
- If a tool call fails (auth, quota, schema drift), include the error
  string in `summary` and return what you can.
"""


log_analyzer_agent = LlmAgent(
    name="log_analyzer",
    model=GEMINI_MODEL,
    description=(
        "Fetches Cloud Logging audit events inside a given time window via "
        "the gcp-log-analyzer MCP server. Returns structured findings; does "
        "not make violation judgements."
    ),
    instruction=LOG_ANALYZER_INSTRUCTION,
    tools=[log_analyzer_mcp],
)
