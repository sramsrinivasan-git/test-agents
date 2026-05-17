"""FastMCP server entrypoint for the GCP log analyzer.

Keeps wiring minimal: instantiate FastMCP, register every tool function
exported by the `tools` package, and run. Each tool's behavior and docstring
lives in its own module under `tools/`.
"""

from __future__ import annotations

from fastmcp import FastMCP

from .tools import ALL_TOOLS

mcp = FastMCP("gcp-log-analyzer")

for tool_fn in ALL_TOOLS:
    mcp.tool()(tool_fn)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
