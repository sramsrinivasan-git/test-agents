"""Runtime configuration, all environment-driven.

Defaults assume the agent runs in a GKE cluster that has the Agent
Sandbox controller installed and two SandboxWarmPool resources defined
(one per MCP server type). Override any value via env vars at the
Deployment / local-shell level.
"""

from __future__ import annotations

import os

GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash")

# Default GCP project the MCP tools fall through to when the orchestrator
# doesn't override `project_id` per-call.
GOOGLE_CLOUD_PROJECT: str | None = os.environ.get("GOOGLE_CLOUD_PROJECT")

APP_NAME = "internal_auditor"

# ----- Sandbox / MCP wiring -------------------------------------------------

# "cluster" (default) - claim a fresh sandboxed MCP server pod from the
#                      named warm pool for every specialist tool call,
#                      release on completion. Requires the Agent Sandbox
#                      controller installed in the cluster and RBAC
#                      letting this pod's ServiceAccount manage
#                      SandboxClaim resources.
# "local"   - skip claim semantics and connect to a static MCP server
#             URL (the *_MCP_URL env vars below). Useful for `adk web`
#             local development with a port-forward to an MCP server
#             pod, or for unit tests.
SANDBOX_MODE: str = os.environ.get("SANDBOX_MODE", "cluster")

SANDBOX_NAMESPACE: str = os.environ.get("SANDBOX_NAMESPACE", "default")

# Warm pool names per MCP server type. Must match the SandboxWarmPool
# resources in deployment/k8s/sandbox-*.yaml.
GCP_LOG_ANALYZER_WARMPOOL: str = os.environ.get(
    "GCP_LOG_ANALYZER_WARMPOOL", "gcp-log-analyzer-warmpool"
)
GCP_CLOUD_ASSET_WARMPOOL: str = os.environ.get(
    "GCP_CLOUD_ASSET_WARMPOOL", "gcp-cloud-asset-warmpool"
)

# Port the MCP servers listen on inside their sandbox pods. Matches the
# Dockerfile EXPOSE on the MCP server image.
MCP_SERVER_PORT: int = int(os.environ.get("MCP_SERVER_PORT", "8080"))

# Local-mode fallback URLs. Only read when SANDBOX_MODE=local. Set these
# to your port-forwarded endpoints, e.g.
#   kubectl -n mcp-servers port-forward svc/gcp-log-analyzer-mcp 18080:8080
#   export GCP_LOG_ANALYZER_MCP_URL=http://localhost:18080/mcp
GCP_LOG_ANALYZER_MCP_URL: str = os.environ.get(
    "GCP_LOG_ANALYZER_MCP_URL", "http://localhost:18080/mcp"
)
GCP_CLOUD_ASSET_MCP_URL: str = os.environ.get(
    "GCP_CLOUD_ASSET_MCP_URL", "http://localhost:18081/mcp"
)
