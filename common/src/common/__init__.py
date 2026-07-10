"""Shared runtime for AaaS agents running on the GKE Agent Sandbox cluster.

Reusable, agent-agnostic building blocks:

- `common.config`   - cluster/runtime knobs (sandbox mode, namespace,
                      MCP port, claim TTL).
- `common.sandbox`  - per-call SandboxClaim lifecycle (claim_mcp_endpoint).
- `common.runner`   - run a one-shot ADK agent turn (run_agent).

Agents are served by ADK's own `adk api_server`, so there is no
HTTP-serving code here. Agent-specific concerns (instructions, output
schemas, which warm pools to use) stay in each agent package.
"""
