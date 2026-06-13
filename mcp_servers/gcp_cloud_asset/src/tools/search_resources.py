"""Tool: full-text search across GCP resources in a scope."""

from __future__ import annotations

from typing import Any

from google.cloud import asset_v1

from gcp_cloud_asset.common import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    get_client,
    resolve_scope,
    resource_to_dict,
)


def search_resources(
    query: str = "",
    asset_types: list[str] | None = None,
    scope: str | None = None,
    project_id: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    order_by: str = "",
) -> dict[str, Any]:
    """Full-text search across GCP resources within a project, folder, or org.

    Searches resource metadata (name, display name, description, labels,
    location, network tags) using the Cloud Asset Inventory. This is the
    right first tool when you want to find what resources exist matching
    some criteria.

    When to use:
      - "Find all Cloud SQL instances in project X."
      - "Which GKE clusters are in us-central1?"
      - "Show me all resources labelled env=prod."
      - Discovering what asset types are present before deeper analysis.

    Args:
        query: Free-text search query. Supports field-qualified predicates:
            - 'name:my-bucket'
            - 'labels.env=prod'
            - 'location:us-central1'
            - 'state:ACTIVE'
            Omit or pass '' to list all resources (subject to page_size).
        asset_types: Optional list of asset types to restrict the search, e.g.
            ['compute.googleapis.com/Instance',
             'storage.googleapis.com/Bucket',
             'container.googleapis.com/Cluster'].
            Omit to search all asset types.
        scope: Resource name of the search scope. One of:
            - 'projects/<id-or-number>'
            - 'folders/<folder-number>'
            - 'organizations/<org-number>'
            Falls back to project_id / GOOGLE_CLOUD_PROJECT.
        project_id: GCP project ID or number. Used when scope is not given.
            Falls back to GOOGLE_CLOUD_PROJECT env var.
        page_size: Maximum resources to return (capped at 500). Default 100.
        order_by: Comma-separated field list to sort by, e.g.
            'location,name'. Append ' DESC' for descending. Default: API
            default ordering.

    Returns:
        dict with keys:
            - scope (str): the scope queried.
            - query (str): the query used.
            - count (int): number of resources returned.
            - resources (list[dict]): each entry has name, asset_type,
              project, folders, organization, display_name, description,
              location, labels, state, create_time, update_time.
    """
    resolved_scope = resolve_scope(scope, project_id)
    client = get_client()
    request = asset_v1.SearchAllResourcesRequest(
        scope=resolved_scope,
        query=query,
        asset_types=asset_types or [],
        page_size=min(page_size, MAX_PAGE_SIZE),
        order_by=order_by,
    )
    results = []
    for resource in client.search_all_resources(request=request):
        results.append(resource_to_dict(resource))
        if len(results) >= page_size:
            break
    return {
        "scope": resolved_scope,
        "query": query,
        "count": len(results),
        "resources": results,
    }
