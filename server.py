"""FastMCP server exposing Google Cloud Logging analysis tools."""

from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp import FastMCP
from google.cloud import logging_v2
from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client

DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000

mcp = FastMCP("gcp-log-analyzer")


def _client() -> LoggingServiceV2Client:
    return logging_v2.Client(project=DEFAULT_PROJECT).logging_api._gapic_api


def _resolve_project(project_id: str | None) -> str:
    project = project_id or DEFAULT_PROJECT
    if not project:
        raise ValueError(
            "project_id is required (or set GOOGLE_CLOUD_PROJECT in the environment)."
        )
    return project


def _time_filter(hours: float) -> str:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return f'timestamp >= "{since.isoformat().replace("+00:00", "Z")}"'


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    payload = entry.json_payload or entry.proto_payload or entry.text_payload
    if hasattr(payload, "items"):
        payload = dict(payload)
    return {
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "severity": logging_v2.LogSeverity(entry.severity).name if entry.severity else "DEFAULT",
        "log_name": entry.log_name,
        "resource_type": entry.resource.type if entry.resource else None,
        "resource_labels": dict(entry.resource.labels) if entry.resource else {},
        "labels": dict(entry.labels) if entry.labels else {},
        "trace": entry.trace or None,
        "insert_id": entry.insert_id,
        "payload": payload,
    }


def _list_entries(
    project_id: str,
    filter_: str,
    page_size: int,
    order_by: str = "timestamp desc",
) -> list[dict[str, Any]]:
    client = _client()
    request = logging_v2.ListLogEntriesRequest(
        resource_names=[f"projects/{project_id}"],
        filter=filter_,
        order_by=order_by,
        page_size=min(page_size, MAX_PAGE_SIZE),
    )
    response = client.list_log_entries(request=request)
    results: list[dict[str, Any]] = []
    for entry in response:
        results.append(_entry_to_dict(entry))
        if len(results) >= page_size:
            break
    return results


@mcp.tool()
def query_logs(
    filter: str,
    project_id: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    order_by: str = "timestamp desc",
) -> dict[str, Any]:
    """Run an advanced-filter query against Cloud Logging.

    See https://cloud.google.com/logging/docs/view/logging-query-language
    for filter syntax. Example filter:
      'severity>=ERROR AND resource.type="cloud_run_revision"'
    """
    project = _resolve_project(project_id)
    entries = _list_entries(project, filter, page_size, order_by)
    return {"project_id": project, "count": len(entries), "entries": entries}


@mcp.tool()
def recent_errors(
    hours: float = 1.0,
    project_id: str | None = None,
    min_severity: str = "ERROR",
    resource_type: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """Fetch recent error-level (or higher) log entries within a time window."""
    project = _resolve_project(project_id)
    parts = [f"severity>={min_severity}", _time_filter(hours)]
    if resource_type:
        parts.append(f'resource.type="{resource_type}"')
    entries = _list_entries(project, " AND ".join(parts), page_size)
    return {
        "project_id": project,
        "window_hours": hours,
        "min_severity": min_severity,
        "count": len(entries),
        "entries": entries,
    }


@mcp.tool()
def summarize_errors(
    hours: float = 24.0,
    project_id: str | None = None,
    min_severity: str = "ERROR",
    top_n: int = 10,
    group_by: str = "resource_type",
) -> dict[str, Any]:
    """Group recent errors by resource_type, log_name, or severity and return top buckets."""
    if group_by not in {"resource_type", "log_name", "severity"}:
        raise ValueError("group_by must be one of: resource_type, log_name, severity")
    project = _resolve_project(project_id)
    filter_ = f"severity>={min_severity} AND {_time_filter(hours)}"
    entries = _list_entries(project, filter_, MAX_PAGE_SIZE)
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


@mcp.tool()
def severity_histogram(
    hours: float = 24.0,
    project_id: str | None = None,
    resource_type: str | None = None,
) -> dict[str, Any]:
    """Return a count of log entries grouped by severity over the given time window."""
    project = _resolve_project(project_id)
    parts = [_time_filter(hours)]
    if resource_type:
        parts.append(f'resource.type="{resource_type}"')
    entries = _list_entries(project, " AND ".join(parts), MAX_PAGE_SIZE)
    counter: Counter[str] = Counter(e["severity"] for e in entries)
    return {
        "project_id": project,
        "window_hours": hours,
        "resource_type": resource_type,
        "total": len(entries),
        "by_severity": dict(counter),
    }


@mcp.tool()
def list_log_names(project_id: str | None = None) -> dict[str, Any]:
    """List log names that have entries in the given project."""
    project = _resolve_project(project_id)
    client = _client()
    request = logging_v2.ListLogsRequest(parent=f"projects/{project}")
    names = [name for name in client.list_logs(request=request)]
    return {"project_id": project, "count": len(names), "log_names": names}


@mcp.tool()
def top_error_messages(
    hours: float = 24.0,
    project_id: str | None = None,
    min_severity: str = "ERROR",
    top_n: int = 10,
) -> dict[str, Any]:
    """Return the most frequent textPayload/message values among recent errors."""
    project = _resolve_project(project_id)
    filter_ = f"severity>={min_severity} AND {_time_filter(hours)}"
    entries = _list_entries(project, filter_, MAX_PAGE_SIZE)
    messages: Counter[str] = Counter()
    for e in entries:
        payload = e.get("payload")
        if isinstance(payload, str):
            messages[payload[:300]] += 1
        elif isinstance(payload, dict):
            msg = payload.get("message") or payload.get("error") or payload.get("msg")
            if msg:
                messages[str(msg)[:300]] += 1
    return {
        "project_id": project,
        "window_hours": hours,
        "min_severity": min_severity,
        "total_matched": len(entries),
        "top_messages": [
            {"message": m, "count": c} for m, c in messages.most_common(top_n)
        ],
    }


if __name__ == "__main__":
    mcp.run()
