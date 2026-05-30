"""Shared helpers for the GCP Cloud Asset MCP tools.

Centralizes the Asset client, scope resolution, and proto-to-dict
normalization so each tool module stays focused on its own behavior.
"""

from __future__ import annotations

import os
from typing import Any

from google.cloud import asset_v1

DEFAULT_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
DEFAULT_PAGE_SIZE = 100
MAX_PAGE_SIZE = 500


def get_client() -> asset_v1.AssetServiceClient:
    """Return a Cloud Asset gapic client using Application Default Credentials."""
    return asset_v1.AssetServiceClient()


def resolve_scope(scope: str | None, project_id: str | None) -> str:
    """Resolve the asset scope string.

    Accepts an explicit `scope` (e.g. 'projects/my-proj',
    'folders/123456', 'organizations/987654'), or falls back to building
    a project scope from `project_id` / GOOGLE_CLOUD_PROJECT.
    """
    if scope:
        return scope
    project = project_id or DEFAULT_PROJECT
    if not project:
        raise ValueError(
            "scope or project_id is required (or set GOOGLE_CLOUD_PROJECT)."
        )
    if not project.startswith("projects/"):
        project = f"projects/{project}"
    return project


def resource_to_dict(resource: Any) -> dict[str, Any]:
    """Convert a ResourceSearchResult proto to a plain dict."""
    return {
        "name": resource.name,
        "asset_type": resource.asset_type,
        "project": resource.project,
        "folders": list(resource.folders),
        "organization": resource.organization,
        "display_name": resource.display_name,
        "description": resource.description,
        "location": resource.location,
        "labels": dict(resource.labels),
        "network_tags": list(resource.tags_keys if hasattr(resource, "tags_keys") else []),
        "state": resource.state,
        "create_time": resource.create_time.isoformat() if resource.create_time else None,
        "update_time": resource.update_time.isoformat() if resource.update_time else None,
    }


def iam_policy_to_dict(result: Any) -> dict[str, Any]:
    """Convert an IamPolicySearchResult proto to a plain dict."""
    bindings = []
    if result.policy and result.policy.bindings:
        for b in result.policy.bindings:
            bindings.append({
                "role": b.role,
                "members": list(b.members),
                "condition": b.condition.expression if b.condition else None,
            })
    return {
        "resource": result.resource,
        "asset_type": result.asset_type,
        "project": result.project,
        "folders": list(result.folders),
        "organization": result.organization,
        "policy_bindings": bindings,
        "explanation": {
            k: list(v.memberships.keys())
            for k, v in result.explanation.matched_permissions.items()
        } if result.explanation else {},
    }


def asset_to_dict(asset: Any) -> dict[str, Any]:
    """Convert an Asset proto (from list_assets) to a plain dict."""
    resource = None
    if asset.resource:
        resource = {
            "version": asset.resource.version,
            "discovery_document_uri": asset.resource.discovery_document_uri,
            "discovery_name": asset.resource.discovery_name,
            "resource_url": asset.resource.resource_url,
            "parent": asset.resource.parent,
            "data": dict(asset.resource.data) if asset.resource.data else {},
            "location": asset.resource.location,
        }
    iam_policy = None
    if asset.iam_policy and asset.iam_policy.bindings:
        iam_policy = [
            {"role": b.role, "members": list(b.members)}
            for b in asset.iam_policy.bindings
        ]
    return {
        "name": asset.name,
        "asset_type": asset.asset_type,
        "resource": resource,
        "iam_policy": iam_policy,
        "ancestors": list(asset.ancestors),
        "update_time": asset.update_time.isoformat() if asset.update_time else None,
    }
