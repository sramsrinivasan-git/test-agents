"""Tool: bucket recent errors by resource_type, log_name, or severity."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ..gcp import MAX_PAGE_SIZE, list_entries, resolve_project, time_filter


def summarize_errors(
    hours: float = 24.0,
    project_id: str | None = None,
    min_severity: str = "ERROR",
    top_n: int = 10,
    group_by: str = "resource_type",
) -> dict[str, Any]:
    """Group recent errors into buckets to find where failures cluster.

    Answers "which service / log / severity is responsible for most of the
    errors?" without dumping individual entries. Pair with `recent_errors`
    or `query_logs` to then inspect the worst bucket in detail.

    When to use:
      - Initial triage on a noisy project: which component is loudest?
      - Before/after a deploy: did one resource type spike?
      - Reporting: "top 5 noisiest services in the last 24h".

    Args:
        hours: Look-back window in hours. Default 24.0.
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT.
        min_severity: Minimum severity to include (see `recent_errors`).
            Default 'ERROR'.
        top_n: Number of buckets to return, sorted by count desc. Default 10.
        group_by: Bucketing dimension. One of:
            - 'resource_type' (default): e.g. cloud_run_revision, k8s_container.
            - 'log_name': full log resource name.
            - 'severity': ERROR / CRITICAL / ALERT / EMERGENCY breakdown.

    Returns:
        dict with keys:
            - project_id, window_hours, min_severity, group_by (echo).
            - total_matched (int): total entries considered (capped at 1000).
            - buckets (list[dict]): [{ 'key': str, 'count': int }, ...]
              sorted by count descending.
    """
    if group_by not in {"resource_type", "log_name", "severity"}:
        raise ValueError("group_by must be one of: resource_type, log_name, severity")
    project = resolve_project(project_id)
    filter_ = f"severity>={min_severity} AND {time_filter(hours)}"
    entries = list_entries(project, filter_, MAX_PAGE_SIZE)
    counter: Counter[str] = Counter(str(e.get(group_by) or "unknown") for e in entries)
    return {
        "project_id": project,
        "window_hours": hours,
        "min_severity": min_severity,
        "group_by": group_by,
        "total_matched": len(entries),
        "buckets": [
            {"key": key, "count": count} for key, count in counter.most_common(top_n)
        ],
    }
