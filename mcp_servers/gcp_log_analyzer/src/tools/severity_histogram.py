"""Tool: count log entries grouped by severity over a time window."""

from __future__ import annotations

from collections import Counter
from typing import Any

from gcp_log_analyzer.common import MAX_PAGE_SIZE, list_entries, resolve_project, time_filter


def severity_histogram(
    hours: float = 24.0,
    project_id: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    """Count log entries grouped by severity over a time window.

    Gives a quick health snapshot: how many INFO vs WARNING vs ERROR vs
    CRITICAL entries are flowing. Useful as a baseline check before any
    deeper investigation.

    When to use:
      - "Is the error rate elevated right now?"
      - Comparing two time windows (call twice with different `hours`).
      - Scoping to one resource to check a specific service's health.

    Args:
        hours: Look-back window in hours. Default 24.0.
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT.
        resource_type: Optional GCP resource type to scope to (e.g.
            'cloud_run_revision'). Omit to count across the whole project.

    Returns:
        dict with keys:
            - project_id, window_hours, resource_type (echo).
            - total (int): total entries considered (capped at 1000).
            - by_severity (dict[str, int]): { 'ERROR': 42, 'INFO': 800, ... }.
              Note: results are capped at 1000 entries, so on very high-volume
              projects this is a sample, not a true total — narrow with
              `resource_type` for accuracy.
    """
    project = resolve_project(project_id)
    parts = [time_filter(hours)]
    if resource_type:
        parts.append(f'resource.type="{resource_type}"')
    entries = list_entries(project, " AND ".join(parts), MAX_PAGE_SIZE)
    counter: Counter[str] = Counter(e["severity"] for e in entries)
    return {
        "project_id": project,
        "window_hours": hours,
        "resource_type": resource_type,
        "total": len(entries),
        "by_severity": dict(counter),
    }
