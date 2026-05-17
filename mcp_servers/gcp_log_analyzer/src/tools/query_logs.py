"""Tool: run a raw Cloud Logging advanced-filter query."""

from __future__ import annotations

from typing import Any

from gcp_log_analyzer.common import DEFAULT_PAGE_SIZE, list_entries, resolve_project


def query_logs(
    filter: str,
    project_id: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    order_by: str = "timestamp desc",
) -> dict[str, Any]:
    """Run a raw Cloud Logging advanced-filter query and return matching entries.

    Use this when you already know the exact filter you want (or need a
    combination not covered by the other tools). The filter language is
    Google's Logging Query Language:
    https://cloud.google.com/logging/docs/view/logging-query-language.

    When to use:
      - Investigating a specific resource, log name, HTTP status, or trace ID.
      - Combining multiple conditions (severity + resource + time + labels).
      - Reproducing a saved query from the Cloud Logging UI.

    Args:
        filter: Cloud Logging advanced filter expression. Examples:
            - 'severity>=ERROR AND resource.type="cloud_run_revision"'
            - 'logName="projects/p/logs/run.googleapis.com%2Frequests"
               AND httpRequest.status>=500'
            - 'resource.type="k8s_container"
               AND resource.labels.namespace_name="prod"
               AND timestamp>="2026-05-17T00:00:00Z"'
            Note: timestamp filters dramatically reduce cost/latency; include
            one whenever possible.
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT env var.
        page_size: Maximum entries to return (capped at 1000). Default 100.
        order_by: 'timestamp desc' (newest first, default) or 'timestamp asc'.

    Returns:
        dict with keys:
            - project_id (str): the project queried.
            - count (int): number of entries returned.
            - entries (list[dict]): each entry has timestamp, severity,
              log_name, resource_type, resource_labels, labels, trace,
              insert_id, and payload (text, JSON, or proto-derived dict).
    """
    project = resolve_project(project_id)
    entries = list_entries(project, filter, page_size, order_by)
    return {"project_id": project, "count": len(entries), "entries": entries}
