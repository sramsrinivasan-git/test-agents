"""Smoke tests that don't hit GCP — verify wiring only."""

from mcp_servers.gcp_log_analyzer.tools import ALL_TOOLS


def test_all_tools_have_docstrings():
    for fn in ALL_TOOLS:
        assert fn.__doc__, f"{fn.__name__} is missing a docstring (LLM needs it)"


def test_all_tools_have_unique_names():
    names = [fn.__name__ for fn in ALL_TOOLS]
    assert len(names) == len(set(names)), f"duplicate tool names: {names}"


def test_server_registers_every_tool():
    from mcp_servers.gcp_log_analyzer.server import mcp

    registered = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {fn.__name__ for fn in ALL_TOOLS}
    assert expected.issubset(registered), f"missing: {expected - registered}"
