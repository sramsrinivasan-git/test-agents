"""Audit-specific configuration, env-driven.

Cluster/runtime knobs (sandbox mode, namespace, MCP port, claim TTL)
live in `common.config`. This module holds only what's specific to the
Internal Auditor: the model, the default project, and which warm pools
its specialists claim from.
"""

from __future__ import annotations

import os

# Per-agent Gemini model selection. Env var names (PRO_MODEL / FLASH_MODEL)
# match the platform-standard vars injected by the agent-spoke Terraform
# module, so every agent selects models the same way.
# - Orchestrator runs Pro: it coordinates, merges findings, and (with
#   the future Policy Agent) drives the replan loop - all reasoning-
#   heavy steps that benefit from the stronger model.
# - Specialists run Flash: their job is to pick the right MCP tool
#   and translate the orchestrator's brief into a tool call. Cheaper /
#   faster suits this well; the LLM isn't doing deep reasoning.
ORCHESTRATOR_MODEL: str = os.environ.get("PRO_MODEL", "gemini-pro-latest")
SPECIALIST_MODEL: str = os.environ.get("FLASH_MODEL", "gemini-flash-latest")

# Default GCP project the MCP tools fall through to when the orchestrator
# doesn't override `project_id` per-call.
GOOGLE_CLOUD_PROJECT: str | None = os.environ.get("GOOGLE_CLOUD_PROJECT")

APP_NAME = "internal_auditor"

# Warm pool names per MCP server type. Must match the names of the
# SandboxWarmPool resources the MCP servers are deployed under (in the
# `agent-sandbox` namespace; deployed + owned separately from this repo).
GCP_LOG_ANALYZER_WARMPOOL: str = os.environ.get(
    "GCP_LOG_ANALYZER_WARMPOOL", "gcp-log-analyzer-warmpool-mcp"
)
GCP_CLOUD_ASSET_WARMPOOL: str = os.environ.get(
    "GCP_CLOUD_ASSET_WARMPOOL", "gcp-cloud-asset-warmpool-mcp"
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
