"""Smoke tests: confirm the agents and tools build without raising.

Doesn't hit the MCP servers, the Gemini API, or the Kubernetes API.
The per-call sandbox claim only fires when a specialist function is
awaited, so importing alone is safe.
"""

from __future__ import annotations

import inspect


def test_root_agent_exposes_both_specialist_function_tools() -> None:
    from internal_auditor import root_agent

    assert root_agent.name == "orchestrator"
    tool_names = {t.name for t in root_agent.tools}
    assert "log_analyzer" in tool_names
    assert "asset_inspector" in tool_names


def test_log_analyzer_specialist_function_is_async() -> None:
    from internal_auditor.log_analyzer import log_analyzer

    assert inspect.iscoroutinefunction(log_analyzer)


def test_asset_inspector_specialist_function_is_async() -> None:
    from internal_auditor.asset_inspector import asset_inspector

    assert inspect.iscoroutinefunction(asset_inspector)


def test_sandbox_helper_is_async_context_manager_factory() -> None:
    from internal_auditor.sandbox import claim_mcp_endpoint

    # Calling it returns an async context manager (no actual claim
    # happens until __aenter__ runs).
    cm = claim_mcp_endpoint("fake-pool", local_fallback_url="http://x/mcp")
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")
