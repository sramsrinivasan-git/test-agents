"""Tool: surface the most frequent error message strings in recent logs."""

from __future__ import annotations

from collections import Counter
from typing import Any

from gcp_log_analyzer.common import MAX_PAGE_SIZE, list_entries, resolve_project, time_filter


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
    project = resolve_project(project_id)
    filter_ = f"severity>={min_severity} AND {time_filter(hours)}"
    entries = list_entries(project, filter_, MAX_PAGE_SIZE)
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
