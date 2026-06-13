"""Smoke tests: confirm the agents build without raising.

Doesn't hit the MCP servers or the Gemini API - just verifies that
imports and agent construction work.
"""

from __future__ import annotations


def test_root_agent_imports_and_exposes_both_specialists_as_tools() -> None:
    from internal_auditor import root_agent

    assert root_agent.name == "orchestrator"
    tool_names = {t.name for t in root_agent.tools}
    assert "log_analyzer" in tool_names
    assert "asset_inspector" in tool_names


def test_log_analyzer_has_mcp_toolset() -> None:
    from internal_auditor.log_analyzer import log_analyzer_agent

    assert log_analyzer_agent.name == "log_analyzer"
    assert len(log_analyzer_agent.tools) >= 1


def test_asset_inspector_has_mcp_toolset() -> None:
    from internal_auditor.asset_inspector import asset_inspector_agent

    assert asset_inspector_agent.name == "asset_inspector"
    assert len(asset_inspector_agent.tools) >= 1
