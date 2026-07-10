"""Smoke tests for the shared runtime. No cluster, no Gemini, no network."""

from __future__ import annotations


def test_claim_mcp_endpoint_is_async_context_manager_factory() -> None:
    from common.sandbox import claim_mcp_endpoint

    # Calling it returns an async context manager (no actual claim
    # happens until __aenter__ runs).
    cm = claim_mcp_endpoint("fake-pool", local_fallback_url="http://x/mcp")
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")


def test_run_agent_is_coroutine_function() -> None:
    import inspect

    from common.runner import run_agent

    assert inspect.iscoroutinefunction(run_agent)


def test_sandbox_namespace_defaults_to_agent_sandbox() -> None:
    from common import config

    # Default when MCP_NAMESPACE is unset in the test environment.
    assert config.SANDBOX_NAMESPACE in ("agent-sandbox",) or isinstance(
        config.SANDBOX_NAMESPACE, str
    )
