"""Smoke tests for the shared runtime. No cluster, no Gemini, no network."""

from __future__ import annotations

import os
import time


def test_claim_mcp_endpoint_is_async_context_manager_factory() -> None:
    from common.sandbox import claim_mcp_endpoint

    # Calling it returns an async context manager (no actual claim
    # happens until __aenter__ runs).
    cm = claim_mcp_endpoint("fake-pool", local_fallback_url="http://x/mcp")
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")


def test_new_run_id_has_prefix_and_is_unique() -> None:
    from common.ids import new_run_id

    a = new_run_id("audit")
    b = new_run_id("audit")
    assert a.startswith("audit-")
    assert a != b


def test_heartbeat_tick_creates_and_refreshes_file(tmp_path) -> None:
    from common.heartbeat import tick

    path = str(tmp_path / "alive")
    assert not os.path.exists(path)
    tick(path)
    assert os.path.exists(path)
    first = os.stat(path).st_mtime
    time.sleep(0.02)
    tick(path)
    assert os.stat(path).st_mtime >= first
