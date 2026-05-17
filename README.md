# AaaS workspace (sample)

This repo demonstrates a uv-workspace monorepo layout for an "Agents as a
Service" project. Drop the `mcp_servers/gcp_log_analyzer/` subtree into your
real `AaaS-repo` to use it.

## Layout

```
AaaS-repo/
├── agents/                  # one folder per agent, each with its own pyproject.toml
├── mcp_servers/             # one folder per MCP server, each with its own pyproject.toml
│   └── gcp_log_analyzer/
├── common/                  # repo-wide shared code
├── tests/                   # tests for everything (mirrors the source tree)
├── infra/
├── docs/
├── pyproject.toml           # workspace root (this file)
└── README.md
```

Each member of the workspace is an independently installable Python package
sharing the `mcp_servers.*` (or `agents.*`) namespace via PEP 420.

## Install

```bash
uv sync   # creates .venv at the workspace root and installs every member
```

## Run a specific server

```bash
uv run gcp-log-analyzer-mcp
```

## Members

- [`mcp_servers/gcp_log_analyzer`](./mcp_servers/gcp_log_analyzer/) — GCP Cloud
  Logging analysis.
