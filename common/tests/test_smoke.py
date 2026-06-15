"""Smoke tests for the shared runtime. No cluster, no Gemini, no network."""

from __future__ import annotations


def test_claim_mcp_endpoint_is_async_context_manager_factory() -> None:
    from common.sandbox import claim_mcp_endpoint

    # Calling it returns an async context manager (no actual claim
    # happens until __aenter__ runs).
    cm = claim_mcp_endpoint("fake-pool", local_fallback_url="http://x/mcp")
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")


def test_new_run_id_has_prefix_and_is_unique() -> None:
    from common.serving import new_run_id

    a = new_run_id("audit")
    b = new_run_id("audit")
    assert a.startswith("audit-")
    assert a != b


def test_build_app_exposes_healthz() -> None:
    from common.serving import build_app

    app = build_app("test")
    paths = {route.path for route in app.routes}
    assert "/healthz" in paths
