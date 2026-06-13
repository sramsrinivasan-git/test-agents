"""Log Analyzer specialist.

Each invocation claims a fresh sandboxed gcp-log-analyzer MCP server
pod, runs a one-shot inner LlmAgent against that pod's MCP endpoint,
returns structured findings, and releases the sandbox.

Explicitly does NOT classify any entry as a violation - that's the
future Policy Agent's job per plan.md.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPServerParams,
)

from internal_auditor import config
from internal_auditor._inner_run import run_inner_agent
from internal_auditor.sandbox import claim_mcp_endpoint


LOG_ANALYZER_INSTRUCTION = """\
You are the Log Analyzer specialist inside the Internal Auditor.

Goal: given a time window (and optional filters like resource_type,
service, principal, severity), call the gcp-log-analyzer MCP tools to
fetch the audit log entries that fall inside that window. Return what
you found - nothing more.

Tool selection:
- `recent_errors`        - first reach when the question is "anything
                           broken in the last N hours?".
- `query_logs`           - when the caller specifies an explicit Cloud
                           Logging filter (severity, resource type,
                           method, principal, log name, etc.).
- `summarize_errors`     - bucket findings by resource_type / log_name /
                           severity for a triage rollup.
- `top_error_messages`   - dedupe a noisy stream into the loudest
                           messages.
- `severity_histogram`   - quick health snapshot of a project / resource.
- `list_log_names`       - exploratory only; when the caller doesn't
                           know what logs exist.

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
- Do NOT label any entry as a violation, suspicious, anomalous, etc.
  You report; the Policy Agent (added later) decides.
- Do NOT invent fields the MCP tool didn't return.
- If the tool returns zero entries, that's a valid result - say so.
- If a tool call fails (auth, quota, schema drift), include the error
  string in `summary` and return what you can.
"""


async def log_analyzer(request: str) -> str:
    """Fetch Cloud Logging audit events for a time window.

    Each call claims a fresh sandboxed gcp-log-analyzer MCP server pod
    from the warm pool, runs the specialist LLM against it, then
    releases the pod.

    Args:
        request: Free-form brief from the orchestrator describing the
            window (lookback hours, optional window_end) and any
            filters (service, method, principal, resource type,
            severity). The specialist LLM will translate this into the
            appropriate MCP tool call.

    Returns:
        JSON string with the specialist's findings.
    """
    async with claim_mcp_endpoint(
        config.GCP_LOG_ANALYZER_WARMPOOL,
        local_fallback_url=config.GCP_LOG_ANALYZER_MCP_URL,
    ) as endpoint:
        toolset = MCPToolset(
            connection_params=StreamableHTTPServerParams(url=endpoint),
        )
        inner_agent = LlmAgent(
            name="log_analyzer",
            model=config.GEMINI_MODEL,
            description="Cloud Logging audit-event specialist.",
            instruction=LOG_ANALYZER_INSTRUCTION,
            tools=[toolset],
        )
        return await run_inner_agent(inner_agent, request, user_id="log_analyzer")


log_analyzer_tool = FunctionTool(func=log_analyzer)
