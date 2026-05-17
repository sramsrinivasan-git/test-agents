"""Tool: enumerate the distinct log names in a project."""

from __future__ import annotations

from typing import Any

from google.cloud import logging_v2

from ..gcp import get_client, resolve_project


def list_log_names(project_id: str | None = None) -> dict[str, Any]:
    """Enumerate the distinct log names that have entries in a project.

    Helps discover what logs exist before constructing a `query_logs` filter.
    Returned values are full resource names like
    'projects/my-proj/logs/run.googleapis.com%2Fstdout' that can be plugged
    directly into a `logName=` filter clause.

    When to use:
      - First-time exploration of an unfamiliar project.
      - Confirming the exact log name to use in a filter (case- and
        URL-encoding sensitive).

    Args:
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT.

    Returns:
        dict with keys:
            - project_id (str).
            - count (int): number of log names found.
            - log_names (list[str]): full log resource names.
    """
    project = resolve_project(project_id)
    client = get_client()
    request = logging_v2.ListLogsRequest(parent=f"projects/{project}")
    names = [name for name in client.list_logs(request=request)]
    return {"project_id": project, "count": len(names), "log_names": names}
