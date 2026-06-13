"""Runtime configuration, all environment-driven.

Defaults are tuned for the GKE deployment: in-cluster MCP server DNS
names and `gemini-3-flash` as the model. Override any value via env vars
at the Deployment / local-shell level.
"""

from __future__ import annotations

import os

GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash")

# In-cluster URL of the gcp-log-analyzer MCP server. The default assumes
# the MCP server is deployed as a Service named `gcp-log-analyzer-mcp`
# in the `mcp-servers` namespace and exposes the streamable-http endpoint
# at /mcp on port 8080. Override with GCP_LOG_ANALYZER_MCP_URL when
# running locally against a port-forward or a different layout.
GCP_LOG_ANALYZER_MCP_URL: str = os.environ.get(
    "GCP_LOG_ANALYZER_MCP_URL",
    "http://gcp-log-analyzer-mcp.mcp-servers.svc.cluster.local:8080/mcp",
)

# Same convention for the gcp-cloud-asset MCP server.
GCP_CLOUD_ASSET_MCP_URL: str = os.environ.get(
    "GCP_CLOUD_ASSET_MCP_URL",
    "http://gcp-cloud-asset-mcp.mcp-servers.svc.cluster.local:8080/mcp",
)

# Default GCP project the MCP tools fall through to when the orchestrator
# doesn't override `project_id` per-call.
GOOGLE_CLOUD_PROJECT: str | None = os.environ.get("GOOGLE_CLOUD_PROJECT")

APP_NAME = "internal_auditor"
