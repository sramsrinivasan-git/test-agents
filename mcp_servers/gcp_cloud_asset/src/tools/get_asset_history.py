"""Tool: fetch the change history of a specific asset over a time window."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import asset_v1
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_cloud_asset.common import get_client, resolve_scope


def get_asset_history(
    asset_names: list[str],
    content_type: str = "RESOURCE",
    hours: float = 24.0,
    start_time: str | None = None,
    end_time: str | None = None,
    scope: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Fetch the change history of specific assets over a time window.

    Returns a sequence of temporal asset snapshots showing how a resource's
    configuration or IAM policy changed over time. Each snapshot records the
    state at the moment the asset changed.

    When to use:
      - "What changed on GCS bucket my-bucket in the last 24 hours?"
      - "Show me the IAM policy history for this service account."
      - Post-incident: "What was the state of this VM before the outage?"
      - Drift detection: comparing current state to a known-good snapshot.

    Note: Cloud Asset Inventory retains history for up to 35 days.

    Args:
        asset_names: List of full asset resource names to fetch history for.
            Examples:
            - '//storage.googleapis.com/projects/_/buckets/my-bucket'
            - '//compute.googleapis.com/projects/p/zones/us-c1-a/instances/vm1'
            - '//iam.googleapis.com/projects/p/serviceAccounts/sa@p.iam.gserviceaccount.com'
            Up to 100 names per call.
        content_type: What content to fetch history for. One of:
            - 'RESOURCE' (default): resource configuration snapshots.
            - 'IAM_POLICY': IAM policy snapshots.
        hours: Look-back window in hours from now (used when start_time is
            not given). Default 24.0. Maximum effective window is 35 days
            (840 hours).
        start_time: RFC-3339 start of the time window, e.g.
            '2026-05-01T00:00:00Z'. Overrides `hours` when provided.
        end_time: RFC-3339 end of the time window. Defaults to now.
        scope: Resource name of the parent scope. One of:
            - 'projects/<id-or-number>'
            - 'folders/<folder-number>'
            - 'organizations/<org-number>'
            Falls back to project_id / GOOGLE_CLOUD_PROJECT.
        project_id: GCP project ID. Used when scope is not given.
            Falls back to GOOGLE_CLOUD_PROJECT env var.

    Returns:
        dict with keys:
            - scope (str): the scope queried.
            - content_type (str): the content type requested.
            - window_start (str): ISO-8601 start of the window.
            - window_end (str): ISO-8601 end of the window.
            - assets (list[dict]): one entry per asset name, each with:
                - name (str): asset resource name.
                - asset_type (str): asset type.
                - history (list[dict]): chronological snapshots, each with
                  update_time, deleted (bool), resource or iam_policy data.
    """
    resolved_scope = resolve_scope(scope, project_id)
    client = get_client()

    now = datetime.now(timezone.utc)
    if end_time:
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    else:
        end_dt = now

    if start_time:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00")).astimezone(timezone.utc)
    else:
        start_dt = end_dt - timedelta(hours=hours)

    def _to_timestamp(dt: datetime) -> Timestamp:
        ts = Timestamp()
        ts.FromDatetime(dt)
        return ts

    content_type_enum = getattr(asset_v1.ContentType, content_type, asset_v1.ContentType.RESOURCE)

    request = asset_v1.BatchGetAssetsHistoryRequest(
        parent=resolved_scope,
        asset_names=asset_names,
        content_type=content_type_enum,
        read_time_window=asset_v1.TimeWindow(
            start_time=_to_timestamp(start_dt),
            end_time=_to_timestamp(end_dt),
        ),
    )
    response = client.batch_get_assets_history(request=request)

    assets_by_name: dict[str, dict[str, Any]] = {}
    for temporal_asset in response.assets:
        name = temporal_asset.asset.name
        asset_type = temporal_asset.asset.asset_type
        if name not in assets_by_name:
            assets_by_name[name] = {"name": name, "asset_type": asset_type, "history": []}

        snapshot: dict[str, Any] = {
            "update_time": temporal_asset.asset.update_time.isoformat()
            if temporal_asset.asset.update_time else None,
            "deleted": temporal_asset.deleted,
            "prior_asset_state": temporal_asset.prior_asset_state.name
            if temporal_asset.prior_asset_state else None,
        }
        if content_type == "RESOURCE" and temporal_asset.asset.resource:
            r = temporal_asset.asset.resource
            snapshot["resource"] = {
                "version": r.version,
                "parent": r.parent,
                "resource_url": r.resource_url,
                "data": dict(r.data) if r.data else {},
            }
        if content_type == "IAM_POLICY" and temporal_asset.asset.iam_policy:
            snapshot["iam_policy"] = [
                {"role": b.role, "members": list(b.members)}
                for b in temporal_asset.asset.iam_policy.bindings
            ]
        assets_by_name[name]["history"].append(snapshot)

    return {
        "scope": resolved_scope,
        "content_type": content_type,
        "window_start": start_dt.isoformat(),
        "window_end": end_dt.isoformat(),
        "assets": list(assets_by_name.values()),
    }
