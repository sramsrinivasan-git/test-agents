"""Tool: list assets of given types in a scope, with optional snapshot time."""

from __future__ import annotations

from typing import Any

from google.cloud import asset_v1
from google.protobuf.timestamp_pb2 import Timestamp

from gcp_cloud_asset.common import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    asset_to_dict,
    get_client,
    resolve_scope,
)


def list_assets(
    asset_types: list[str] | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    content_type: str = "RESOURCE",
    snapshot_time: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> dict[str, Any]:
    """List GCP assets of given types within a scope, optionally at a past point-in-time.

    Returns a snapshot of the asset inventory. Unlike `search_resources`,
    this gives you the full resource data payload (REST resource JSON) and
    is the right tool when you need the actual configuration of resources,
    not just their metadata.

    When to use:
      - "List all GCS buckets in the project with their full configs."
      - "What IAM policies were attached to BigQuery datasets yesterday?"
      - Bulk export of resource configurations for comparison or auditing.
      - Getting the complete list when you know the exact asset type.

    Args:
        asset_types: List of asset types to include. Required for large scopes
            to avoid timeouts. Examples:
            - 'storage.googleapis.com/Bucket'
            - 'compute.googleapis.com/Instance'
            - 'iam.googleapis.com/ServiceAccount'
            - 'cloudresourcemanager.googleapis.com/Project'
            Omit to list all asset types (may be slow in large scopes).
        scope: Resource name of the scope. One of:
            - 'projects/<id-or-number>'
            - 'folders/<folder-number>'
            - 'organizations/<org-number>'
            Falls back to project_id / GOOGLE_CLOUD_PROJECT.
        project_id: GCP project ID or number. Used when scope is not given.
            Falls back to GOOGLE_CLOUD_PROJECT env var.
        content_type: What content to return. One of:
            - 'RESOURCE' (default): the resource configuration.
            - 'IAM_POLICY': IAM policy bindings on each asset.
            - 'ORG_POLICY': org policies.
            - 'ACCESS_POLICY': VPC Service Controls / access policies.
        snapshot_time: Optional RFC-3339 timestamp to snapshot the inventory
            at a past moment, e.g. '2026-05-01T00:00:00Z'. Useful for
            comparing state before/after a change. Defaults to now.
        page_size: Maximum assets to return (capped at 500). Default 100.

    Returns:
        dict with keys:
            - scope (str): the scope queried.
            - content_type (str): the content type requested.
            - snapshot_time (str | None): the snapshot time used.
            - count (int): number of assets returned.
            - assets (list[dict]): each entry has name, asset_type,
              ancestors, update_time, resource (full REST data), and
              iam_policy (if content_type='IAM_POLICY').
    """
    resolved_scope = resolve_scope(scope, project_id)
    client = get_client()

    content_type_enum = getattr(asset_v1.ContentType, content_type, asset_v1.ContentType.RESOURCE)

    read_time = None
    if snapshot_time:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(snapshot_time.replace("Z", "+00:00"))
        read_time = Timestamp()
        read_time.FromDatetime(dt.astimezone(timezone.utc))

    request = asset_v1.ListAssetsRequest(
        parent=resolved_scope,
        asset_types=asset_types or [],
        content_type=content_type_enum,
        page_size=min(page_size, MAX_PAGE_SIZE),
        read_time=read_time,
    )
    assets = []
    for asset in client.list_assets(request=request):
        assets.append(asset_to_dict(asset))
        if len(assets) >= page_size:
            break
    return {
        "scope": resolved_scope,
        "content_type": content_type,
        "snapshot_time": snapshot_time,
        "count": len(assets),
        "assets": assets,
    }
