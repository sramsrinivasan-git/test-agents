"""Per-call sandbox claim helper for sandboxed MCP servers.

Wraps the GKE Agent Sandbox `SandboxClaim` lifecycle in an async context
manager. Yields the in-cluster MCP endpoint URL of the pod the controller
binds to the claim, and tears the claim down (which recycles the pod
back into the warm pool, or destroys it depending on the template's
shutdown policy) when the context exits.

API contract used:
  CRD: SandboxClaim (apiVersion: extensions.agents.x-k8s.io/v1beta1)
  spec: { warmPoolRef: { name: <warmpool-name> } }
  status.sandbox.podIPs[]: bound pod IPs (populated when claim is Ready)

The `k8s-agent-sandbox` PyPI package provides the SandboxClient that
talks to the cluster's Kubernetes API. It handles the wait-until-ready
+ delete-on-terminate machinery for us.

When SANDBOX_MODE=local, this module short-circuits to the static
GCP_*_MCP_URL configured in `config.py` so that `adk web` and unit
tests work without cluster access.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from internal_auditor import config


@asynccontextmanager
async def claim_mcp_endpoint(
    warmpool_name: str,
    *,
    local_fallback_url: str,
) -> AsyncIterator[str]:
    """Yield an MCP server endpoint URL for the duration of one call.

    Args:
        warmpool_name: Name of the SandboxWarmPool to claim from.
        local_fallback_url: URL to return when SANDBOX_MODE=local; lets
            local dev / tests bypass the cluster entirely.

    Yields:
        Endpoint URL string of the bound MCP server, e.g.
        `http://10.4.2.17:8080/mcp`.

    On exit (success or exception) the SandboxClaim is deleted, which
    returns the pod to the warm pool's recycle/replenish loop.
    """
    if config.SANDBOX_MODE == "local":
        yield local_fallback_url
        return

    # Imported lazily so local/test runs don't require the client lib
    # or a kube context.
    from k8s_agent_sandbox import SandboxClient

    client = SandboxClient(namespace=config.SANDBOX_NAMESPACE)
    sandbox = client.create_sandbox(warmpool=warmpool_name)
    try:
        pod_ip = sandbox.pod_ips[0]
        yield f"http://{pod_ip}:{config.MCP_SERVER_PORT}/mcp"
    finally:
        sandbox.terminate()
