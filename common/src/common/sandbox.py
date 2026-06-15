"""Per-call sandbox claim helper for sandboxed MCP servers.

Wraps the GKE Agent Sandbox `SandboxClaim` lifecycle in an async context
manager. Yields the in-cluster MCP endpoint URL of the pod the controller
binds to the claim, and tears the claim down (which recycles the pod
back into the warm pool, or destroys it depending on the template's
shutdown policy) when the context exits.

API (verified against k8s-agent-sandbox 0.4/0.5):
  AsyncSandboxClient(connection_config=...)        # async client
  await client.create_sandbox(warmpool, namespace) # creates the claim,
                                                   # waits for Ready,
                                                   # returns AsyncSandbox
  await sandbox.get_pod_ip() -> str | None         # bound pod IP
  await sandbox.terminate()                         # close + delete claim

We talk to the MCP server directly over the cluster pod network (the
claiming agent runs in-cluster), so we build the URL from the pod IP
ourselves rather than using the client's command/file connectors -
hence SandboxInClusterConnectionConfig(use_pod_ip=True). The MCP-only
pods run no in-pod agent sidecar; that's fine because create_sandbox
opens no data-plane connection and the connectors are never invoked.

A `shutdown_after_seconds` TTL is set on each claim as a backstop: if
the claiming process crashes between claim and terminate(), the
controller reaps the leaked claim instead of pinning a warm-pool slot
forever.

When SANDBOX_MODE=local, this module short-circuits to a static URL the
caller supplies so that `adk web` and unit tests work without cluster
access (and without the k8s-agent-sandbox async deps installed).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from common import config


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

    On exit (success or exception) the sandbox is terminated, which
    closes the client connection and deletes the SandboxClaim, returning
    the pod to the warm pool's recycle/replenish loop.
    """
    if config.SANDBOX_MODE == "local":
        yield local_fallback_url
        return

    # Imported lazily so local/test runs don't require the client lib,
    # its async extras, or a kube context.
    from k8s_agent_sandbox import AsyncSandboxClient, SandboxNotReadyError
    from k8s_agent_sandbox.models import SandboxInClusterConnectionConfig

    client = AsyncSandboxClient(
        connection_config=SandboxInClusterConnectionConfig(use_pod_ip=True),
    )
    sandbox = await client.create_sandbox(
        warmpool=warmpool_name,
        namespace=config.SANDBOX_NAMESPACE,
        shutdown_after_seconds=config.SANDBOX_CLAIM_TTL_SECONDS,
    )
    try:
        pod_ip = await sandbox.get_pod_ip()
        if not pod_ip:
            raise SandboxNotReadyError(
                f"sandbox claimed from {warmpool_name!r} has no pod IP"
            )
        yield f"http://{pod_ip}:{config.MCP_SERVER_PORT}/mcp"
    finally:
        await sandbox.terminate()
