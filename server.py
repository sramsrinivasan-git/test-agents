"""FastMCP server exposing Google Cloud Logging analysis tools.

This server lets an MCP client (e.g. Claude) investigate Google Cloud Platform
logs: run advanced-filter queries, fetch recent errors, build severity
histograms, surface the most frequent error messages, and enumerate logs.

Authentication uses Application Default Credentials (ADC). Set
GOOGLE_CLOUD_PROJECT or pass project_id per call.
"""

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
    """Surface the most frequent error message strings in recent logs.

    Extracts a message from each entry's payload (textPayload, or
    jsonPayload.message / .error / .msg) and counts unique values. Helps
    identify which specific exception or error string is driving incident
    volume.

    When to use:
      - "What's the dominant error right now?"
      - Deduplicating a noisy stream into a short list of distinct failures.
      - Before opening per-entry detail with `query_logs` / `recent_errors`.

    Limitations:
      - Only inspects up to 1000 most recent entries in the window.
      - Messages are truncated to 300 chars for grouping; near-identical
        errors with different IDs / timestamps embedded in the message may
        appear as separate buckets.

    Args:
        hours: Look-back window in hours. Default 24.0.
        project_id: GCP project ID. Falls back to GOOGLE_CLOUD_PROJECT.
        min_severity: Minimum severity to include. Default 'ERROR'.
        top_n: Number of distinct messages to return. Default 10.

    Returns:
        dict with keys:
            - project_id, window_hours, min_severity (echo).
            - total_matched (int): entries considered.
            - top_messages (list[dict]): [{ 'message': str, 'count': int }, ...]
              sorted by count descending.
    """
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
