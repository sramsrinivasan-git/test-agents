"""Tool: full-text search across IAM policies in a scope."""

from __future__ import annotations

from typing import Any

from google.cloud import asset_v1

from gcp_cloud_asset.common import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_client,
    iam_policy_to_dict,
    resolve_scope,
)


def search_iam_policies(
    query: str,
    asset_types: list[str] | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    order_by: str = "",
) -> dict[str, Any]:
    """Full-text search across IAM policies within a project, folder, or org.

    Searches policy bindings (roles, members, conditions) using Cloud Asset
    Inventory. Use this to answer access-related questions without having to
    enumerate every resource manually.

    When to use:
      - "Which resources does serviceAccount:sa@p.iam.gserviceaccount.com
         have access to?"
      - "Find all bindings for roles/editor across the project."
      - "Which resources have allUsers or allAuthenticatedUsers in a binding?"
      - Auditing IAM before a security review.

    Args:
        query: IAM policy search query. Supports field qualifiers:
            - 'policy:roles/storage.admin'
            - 'policy.role.permissions:storage.buckets.delete'
            - 'memberTypes:serviceAccount'
            - 'policy:user:alice@example.com'
            Unlike `search_resources`, a query is required — pass at least
            a role or member filter to avoid returning everything.
        asset_types: Optional list of asset types to restrict the search, e.g.
            ['storage.googleapis.com/Bucket',
             'cloudresourcemanager.googleapis.com/Project'].
            Omit to search all asset types.
        scope: Resource name of the search scope. One of:
            - 'projects/<id-or-number>'
            - 'folders/<folder-number>'
            - 'organizations/<org-number>'
            Falls back to project_id / GOOGLE_CLOUD_PROJECT.
        project_id: GCP project ID or number. Used when scope is not given.
            Falls back to GOOGLE_CLOUD_PROJECT env var.
        page_size: Maximum results to return (capped at 500). Default 100.
        order_by: Comma-separated field list to sort by. Default: API default.

    Returns:
        dict with keys:
            - scope (str): the scope queried.
            - query (str): the query used.
            - count (int): number of results returned.
            - results (list[dict]): each entry has resource, asset_type,
              project, folders, organization, policy_bindings (list of
              {role, members, condition}), and explanation.
    """
    resolved_scope = resolve_scope(scope, project_id)
    client = get_client()
    request = asset_v1.SearchAllIamPoliciesRequest(
        scope=resolved_scope,
        query=query,
        asset_types=asset_types or [],
        page_size=min(page_size, MAX_PAGE_SIZE),
        order_by=order_by,
    )
    results = []
    for result in client.search_all_iam_policies(request=request):
        results.append(iam_policy_to_dict(result))
        if len(results) >= page_size:
            break
    return {
        "scope": resolved_scope,
        "query": query,
        "count": len(results),
        "results": results,
    }
