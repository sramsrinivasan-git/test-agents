"""Tool: fetch recent log entries at or above a given severity."""

from __future__ import annotations

from typing import Any

from ..gcp import DEFAULT_PAGE_SIZE, list_entries, resolve_project, time_filter


def recent_errors(
    hours: float = 1.0,
    project_id: str | None = None,
    min_severity: str = "ERROR",
    resource_type: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Fetch recent log entries at or above a given severity.

    Convenience wrapper around `query_logs` for the most common triage
    question: "what's been failing lately?" Use this as a first step when a
    user reports an incident or asks about current health.

    When to use:
      - "Anything broken in the last hour?"
      - "Show me Cloud Run errors from the past 30 minutes."
      - Initial drill-down before calling `summarize_errors` or
        `top_error_messages`.

    Args:
        hours: Look-back window in hours (fractional allowed, e.g. 0.5).
            Default 1.0.
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT.
        min_severity: Minimum severity to include. One of DEFAULT, DEBUG,
            INFO, NOTICE, WARNING, ERROR, CRITICAL, ALERT, EMERGENCY.
            Default 'ERROR'.
        resource_type: Optional GCP resource type to scope to, e.g.
            'cloud_run_revision', 'k8s_container', 'gce_instance',
            'cloud_function', 'gae_app'. Omit to search all resources.
        page_size: Maximum entries to return (capped at 1000). Default 100.

    Returns:
        dict with keys:
            - project_id, window_hours, min_severity (echo of inputs).
            - count (int): number of entries returned.
            - entries (list[dict]): same shape as `query_logs`.
    """
    project = resolve_project(project_id)
    parts = [f"severity>={min_severity}", time_filter(hours)]
    if resource_type:
        parts.append(f'resource.type="{resource_type}"')
    entries = list_entries(project, " AND ".join(parts), page_size)
    return {
        "project_id": project,
        "window_hours": hours,
        "min_severity": min_severity,
        "count": len(entries),
        "entries": entries,
    }
