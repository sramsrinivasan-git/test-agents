"""Asset Inspector sub-agent.

Snapshots GCP resource state and IAM bindings for a given time window
via the gcp-cloud-asset MCP server. Returns structured findings to the
orchestrator. Like the Log Analyzer, it does NOT classify anything as a
violation - that's the future Policy Agent's job per plan.md.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPServerParams,
)

from internal_auditor.config import GCP_CLOUD_ASSET_MCP_URL, GEMINI_MODEL

asset_inspector_mcp = MCPToolset(
    connection_params=StreamableHTTPServerParams(url=GCP_CLOUD_ASSET_MCP_URL),
)


ASSET_INSPECTOR_INSTRUCTION = """\
You are the Asset Inspector agent inside the Internal Auditor.

Goal: given a time window and optional filters (resource type, project,
IAM role, member), call the gcp-cloud-asset MCP tools to snapshot the
relevant GCP resource state and IAM bindings as of window_end. Return
what you found - nothing more.

Tool selection:
- `search_resources`     - find resources by type / project / name pattern
                           (e.g. all compute.googleapis.com/Firewall in
                           prod-project-01).
- `search_iam_policies`  - find IAM bindings org-wide by role, member, or
                           resource (e.g. who currently holds
                           roles/owner on prod-project-01).
- `list_assets`          - enumerate assets in a scope when you need the
                           full snapshot.
- `analyze_iam_policy`   - "who has effective access to X" / "what can
                           principal Y do" - for resolving a specific
                           access question raised by the orchestrator.
- `get_asset_history`    - change history for a specific resource. Use
                           this when the orchestrator asks "what was the
                           prior IAM role?" during a replan.

Output (JSON, single object - this is your final response):
{
  "tool_used": "<which MCP tool you called>",
  "window_end": "<ISO timestamp the snapshot is anchored at>",
  "filters": { ... what you actually passed ... },
  "total_assets": <int>,
  "assets": [ ... raw entries from the MCP tool, untouched ... ],
  "summary": "<one-paragraph human-readable summary of what you saw>"
}

CRITICAL constraints:
- Do NOT label any binding or resource as a violation, suspicious, over-
  privileged, etc. You report; the Policy Agent (added later) decides.
- Do NOT invent fields the MCP tool didn't return.
- If a tool returns zero assets, say so honestly.
- If a tool call fails (auth, quota, schema drift), put the error string
  in `summary` and return what you can.
"""


asset_inspector_agent = LlmAgent(
    name="asset_inspector",
    model=GEMINI_MODEL,
    description=(
        "Snapshots GCP resource state and IAM bindings via the "
        "gcp-cloud-asset MCP server. Returns structured findings; does "
        "not make violation judgements."
    ),
    instruction=ASSET_INSPECTOR_INSTRUCTION,
    tools=[asset_inspector_mcp],
)
