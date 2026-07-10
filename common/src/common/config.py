"""Cluster/runtime configuration shared by all agents, env-driven.

These are knobs about *where and how* an agent runs on the GKE Agent
Sandbox cluster - not about what any particular agent does. Agent-specific
config (model, warm-pool names, output schemas) lives in the agent package.
"""

from __future__ import annotations

import os

# "cluster" (default) - claim a fresh sandboxed MCP server pod from the
#                      named warm pool for every tool call, release on
#                      completion. Requires the Agent Sandbox controller
#                      installed in the cluster and RBAC letting this
#                      pod's ServiceAccount manage SandboxClaim resources.
# "local"   - skip claim semantics and connect to a static MCP server
#             URL supplied by the caller. Useful for `adk web` local
#             development with a port-forward to an MCP server pod, or
#             for unit tests.
SANDBOX_MODE: str = os.environ.get("SANDBOX_MODE", "cluster")

# Namespace the SandboxWarmPool / SandboxClaim resources live in. Read from
# MCP_NAMESPACE (the platform-standard var an agent passes via the
# agent-spoke module's env_vars), defaulting to `agent-sandbox`.
SANDBOX_NAMESPACE: str = os.environ.get("MCP_NAMESPACE", "agent-sandbox")

# Port the MCP servers listen on inside their sandbox pods. Matches the
# Dockerfile EXPOSE on the MCP server image.
MCP_SERVER_PORT: int = int(os.environ.get("MCP_SERVER_PORT", "8080"))

# Backstop TTL on each SandboxClaim. The happy path deletes the claim
# explicitly when the tool call finishes; this only matters if the
# claiming process crashes mid-call, in which case the controller reaps
# the leaked claim after this many seconds. Must comfortably exceed the
# longest expected single tool call (MCP query + inner-LLM reasoning).
SANDBOX_CLAIM_TTL_SECONDS: int = int(
    os.environ.get("SANDBOX_CLAIM_TTL_SECONDS", "900")
)
