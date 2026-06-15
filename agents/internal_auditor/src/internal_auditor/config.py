"""Audit-specific configuration, env-driven.

Cluster/runtime knobs (sandbox mode, namespace, MCP port, claim TTL)
live in `common.config`. This module holds only what's specific to the
Internal Auditor: the model, the default project, and which warm pools
its specialists claim from.
"""

from __future__ import annotations

import os

GEMINI_MODEL: str = os.environ.get("GEMINI_MODEL", "gemini-3-flash")

# Default GCP project the MCP tools fall through to when the orchestrator
# doesn't override `project_id` per-call.
GOOGLE_CLOUD_PROJECT: str | None = os.environ.get("GOOGLE_CLOUD_PROJECT")

APP_NAME = "internal_auditor"

# Warm pool names per MCP server type. Must match the SandboxWarmPool
# resources in deployment/k8s/sandbox-*.yaml.
GCP_LOG_ANALYZER_WARMPOOL: str = os.environ.get(
    "GCP_LOG_ANALYZER_WARMPOOL", "gcp-log-analyzer-warmpool"
)
GCP_CLOUD_ASSET_WARMPOOL: str = os.environ.get(
    "GCP_CLOUD_ASSET_WARMPOOL", "gcp-cloud-asset-warmpool"
)

# Local-mode fallback URLs. Only read when SANDBOX_MODE=local (see
# common.config). Set these to your port-forwarded endpoints, e.g.
#   kubectl -n mcp-servers port-forward svc/gcp-log-analyzer-mcp 18080:8080
#   export GCP_LOG_ANALYZER_MCP_URL=http://localhost:18080/mcp
GCP_LOG_ANALYZER_MCP_URL: str = os.environ.get(
    "GCP_LOG_ANALYZER_MCP_URL", "http://localhost:18080/mcp"
)
GCP_CLOUD_ASSET_MCP_URL: str = os.environ.get(
    "GCP_CLOUD_ASSET_MCP_URL", "http://localhost:18081/mcp"
)
