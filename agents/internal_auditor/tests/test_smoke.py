"""Smoke tests: confirm the agents build without raising.

Doesn't hit the MCP server or the Gemini API - just verifies that
imports and agent construction work.
"""

from __future__ import annotations


def test_root_agent_imports_and_has_log_analyzer_subagent() -> None:
    from internal_auditor import root_agent

    assert root_agent.name == "orchestrator"
    sub_names = {sa.name for sa in root_agent.sub_agents}
    assert "log_analyzer" in sub_names


def test_log_analyzer_has_mcp_toolset() -> None:
    from internal_auditor.log_analyzer import log_analyzer_agent

    assert log_analyzer_agent.name == "log_analyzer"
    assert len(log_analyzer_agent.tools) >= 1
