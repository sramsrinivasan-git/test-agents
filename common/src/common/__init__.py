"""Shared runtime for AaaS agents running on the GKE Agent Sandbox cluster.

Reusable, agent-agnostic building blocks:

- `common.config`    - cluster/runtime knobs (sandbox mode, namespace,
                       MCP port, claim TTL).
- `common.sandbox`   - per-call SandboxClaim lifecycle (claim_mcp_endpoint).
- `common.runner`    - run a one-shot ADK agent turn (run_agent).
- `common.pubsub`    - long-running Pub/Sub subscriber (run_subscriber).
- `common.heartbeat` - liveness heartbeat for non-HTTP services (tick).
- `common.ids`       - run-id minting (new_run_id).

Agent-specific concerns (instructions, output schemas, message
contracts, which warm pools to use) stay in each agent package.
"""
