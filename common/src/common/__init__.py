"""Shared runtime for AaaS agents running on the GKE Agent Sandbox cluster.

Reusable, agent-agnostic building blocks:

- `common.config`   - cluster/runtime knobs (sandbox mode, namespace,
                      MCP port, claim TTL).
- `common.sandbox`  - per-call SandboxClaim lifecycle (claim_mcp_endpoint).
- `common.runner`   - run a one-shot ADK agent turn (run_agent).
- `common.serving`  - FastAPI scaffolding (build_app, new_run_id, serve).

Agent-specific concerns (instructions, output schemas, HTTP request/
response contracts, which warm pools to use) stay in each agent package.
"""
