"""Tool functions exposed by the GCP Cloud Asset MCP server.

Each module here defines one tool as a plain function. `server.py` is
responsible for registering them with the FastMCP instance, so the tools
themselves remain framework-agnostic and unit-testable.
"""

from gcp_cloud_asset.tools.search_resources import search_resources
from gcp_cloud_asset.tools.search_iam_policies import search_iam_policies
from gcp_cloud_asset.tools.list_assets import list_assets
from gcp_cloud_asset.tools.analyze_iam_policy import analyze_iam_policy
from gcp_cloud_asset.tools.get_asset_history import get_asset_history

ALL_TOOLS = [
    search_resources,
    search_iam_policies,
    list_assets,
    analyze_iam_policy,
    get_asset_history,
]

__all__ = [
    "ALL_TOOLS",
    "search_resources",
    "search_iam_policies",
    "list_assets",
    "analyze_iam_policy",
    "get_asset_history",
]
