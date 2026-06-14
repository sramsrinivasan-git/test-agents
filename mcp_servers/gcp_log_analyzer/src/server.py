"""FastMCP server entrypoint for the GCP log analyzer.

Transport is selected by the MCP_TRANSPORT env var:
  - 'stdio' (default): for local MCP clients launching this as a subprocess.
  - 'streamable-http': for remote deployment - this is what the GKE
    SandboxWarmPool pods run. Listens on $PORT (defaults to 8080).
  - 'sse': older HTTP transport, kept for clients that don't yet speak
    streamable-http.
"""

from __future__ import annotations

import os

from fastmcp import FastMCP

from gcp_log_analyzer.tools import ALL_TOOLS

mcp = FastMCP("gcp-log-analyzer")

for tool_fn in ALL_TOOLS:
    mcp.tool()(tool_fn)


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    else:
        port = int(os.environ.get("PORT", "8080"))
        mcp.run(transport=transport, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
