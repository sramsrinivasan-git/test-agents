"""Shared helpers for the GCP log-analyzer MCP tools.

Centralizes the Cloud Logging client, project resolution, time-window
filter construction, and entry-to-dict normalization so each tool module
stays focused on its own behavior.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import logging_v2
from google.cloud.logging_v2.services.logging_service_v2 import LoggingServiceV2Client

DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 1000


def get_client() -> LoggingServiceV2Client:
    """Return a low-level Cloud Logging gapic client.

    Uses Application Default Credentials. The high-level
    `logging_v2.Client` is created first so ADC / project discovery happens
    consistently with the rest of the google-cloud-logging library.
    """
    return logging_v2.Client(project=DEFAULT_PROJECT).logging_api._gapic_api


def resolve_project(project_id: str | None) -> str:
    """Pick the explicit project_id, or fall back to GOOGLE_CLOUD_PROJECT."""
    project = project_id or DEFAULT_PROJECT
    if not project:
        raise ValueError(
            "project_id is required (or set GOOGLE_CLOUD_PROJECT in the environment)."
        )
    return project


def time_filter(hours: float) -> str:
    """Build a Cloud Logging `timestamp >= ...` clause for the last N hours."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return f'timestamp >= "{since.isoformat().replace("+00:00", "Z")}"'


def entry_to_dict(entry: Any) -> dict[str, Any]:
    """Normalize a Cloud Logging LogEntry into a plain JSON-safe dict."""
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


def list_entries(
    project_id: str,
    filter_: str,
    page_size: int,
    order_by: str = "timestamp desc",
) -> list[dict[str, Any]]:
    """Run a Cloud Logging list_log_entries query and return normalized dicts."""
    client = get_client()
    request = logging_v2.ListLogEntriesRequest(
        resource_names=[f"projects/{project_id}"],
        filter=filter_,
        order_by=order_by,
        page_size=min(page_size, MAX_PAGE_SIZE),
    )
    response = client.list_log_entries(request=request)
    results: list[dict[str, Any]] = []
    for entry in response:
        results.append(entry_to_dict(entry))
        if len(results) >= page_size:
            break
    return results
