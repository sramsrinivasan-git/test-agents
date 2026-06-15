"""Smoke tests: confirm the agents and tools build without raising.

Doesn't hit the MCP servers, the Gemini API, or the Kubernetes API.
The per-call sandbox claim (in common.sandbox) only fires when a
specialist function is awaited, so importing alone is safe.
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
