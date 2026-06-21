"""Asset Inspector specialist.

Each invocation claims a fresh sandboxed gcp-cloud-asset MCP server
pod, runs a one-shot inner LlmAgent against that pod's MCP endpoint,
returns structured findings, and releases the sandbox.

Like the Log Analyzer, it does NOT classify anything as a violation -
that's the future Policy Agent's job per plan.md.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import (
    MCPToolset,
    StreamableHTTPConnectionParams,
)

from common.runner import run_agent
from common.sandbox import claim_mcp_endpoint

from internal_auditor import config, schemas


ASSET_INSPECTOR_INSTRUCTION = f"""\
You are the Asset Inspector specialist inside the Internal Auditor.

Goal: given a time window and optional filters (resource type, project,
IAM role, member), call the gcp-cloud-asset MCP tools to snapshot the
relevant GCP resource state and IAM bindings as of window_end. Return
what you found - nothing more.

Pick the gcp-cloud-asset tool that best fits the brief; each tool's own
description says when to use it. Prefer the narrowest query that answers
the orchestrator's question.

Output (JSON, single object - this is your final response):
{schemas.ASSET_INSPECTOR_FINDINGS}

CRITICAL constraints:
- Do NOT label any binding or resource as a violation, suspicious, over-
  privileged, etc. You report; the Policy Agent (added later) decides.
- Do NOT invent fields the MCP tool didn't return.
- If a tool returns zero assets, say so honestly.
- If a tool call fails (auth, quota, schema drift), put the error string
  in `summary` and return what you can.
"""


async def asset_inspector(request: str) -> str:
    """Snapshot GCP resource state + IAM bindings for a time window.

    Each call claims a fresh sandboxed gcp-cloud-asset MCP server pod
    from the warm pool, runs the specialist LLM against it, then
    releases the pod.

    Args:
        request: Free-form brief from the orchestrator describing the
            snapshot anchor (window_end) and any filters
            (resource_type, project, IAM role, member). The specialist
            LLM will translate this into the appropriate MCP tool call.

    Returns:
        JSON string with the specialist's findings.
    """
    async with claim_mcp_endpoint(
        config.GCP_CLOUD_ASSET_WARMPOOL,
        local_fallback_url=config.GCP_CLOUD_ASSET_MCP_URL,
    ) as endpoint:
        toolset = MCPToolset(
            connection_params=StreamableHTTPConnectionParams(url=endpoint),
        )
        inner_agent = LlmAgent(
            name="asset_inspector",
            model=config.SPECIALIST_MODEL,
            description="GCP resource + IAM snapshot specialist.",
            instruction=ASSET_INSPECTOR_INSTRUCTION,
            tools=[toolset],
        )
        return await run_agent(
            inner_agent, request, app_name=config.APP_NAME, user_id="asset_inspector"
        )


asset_inspector_tool = FunctionTool(func=asset_inspector)
