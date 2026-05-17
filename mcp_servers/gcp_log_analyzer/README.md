# gcp_log_analyzer

FastMCP server exposing Google Cloud Logging as a set of tools an MCP client
(e.g. Claude) can call to query and summarize logs.

## Layout

```
mcp_servers/gcp_log_analyzer/
├── pyproject.toml          # this package's deps + console script
├── README.md               # you are here
├── tests/                  # tests for this server
└── src/                    # the package contents (importable as `gcp_log_analyzer`)
    ├── __init__.py
    ├── server.py           # FastMCP entrypoint, registers every tool
    ├── common.py           # shared helpers (client, filters, normalization)
    └── tools/              # one file per MCP tool
        ├── __init__.py     # exports ALL_TOOLS
        ├── query_logs.py
        ├── recent_errors.py
        ├── summarize_errors.py
        ├── severity_histogram.py
        ├── list_log_names.py
        └── top_error_messages.py
```

The package name is `gcp_log_analyzer` (set in `pyproject.toml` via
`package-dir`), so imports look like:

```python
from gcp_log_analyzer.tools import recent_errors
```

## Tools

- `query_logs(filter, project_id?, page_size?, order_by?)` — raw advanced-filter query.
- `recent_errors(hours, project_id?, min_severity?, resource_type?, page_size?)` —
  fetch recent entries at or above a severity.
- `summarize_errors(hours, project_id?, min_severity?, top_n?, group_by?)` —
  bucket recent errors by `resource_type`, `log_name`, or `severity`.
- `severity_histogram(hours, project_id?, resource_type?)` — counts by severity.
- `top_error_messages(hours, project_id?, min_severity?, top_n?)` — most frequent
  error message strings.
- `list_log_names(project_id?)` — enumerate log names in the project.

## Install (from the workspace root)

```bash
uv sync                                    # installs all workspace members
# or, just this package:
uv pip install -e mcp_servers/gcp_log_analyzer
```

## Configure GCP

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
```

The caller needs `roles/logging.viewer` (or `roles/logging.privateLogViewer`
for data-access logs).

## Run

```bash
uv run gcp-log-analyzer-mcp
# or
uv run python -m gcp_log_analyzer.server
```

## Test

```bash
uv run pytest mcp_servers/gcp_log_analyzer/tests/
```

## Adding a new tool

1. Create `src/tools/my_tool.py` with a single function and a detailed
   docstring (purpose, when-to-use, args, returns).
2. Import it and append to `ALL_TOOLS` in `src/tools/__init__.py`.
3. `server.py` registers it automatically on the next start.

## Filter examples

```text
severity>=ERROR AND resource.type="cloud_run_revision"
resource.type="k8s_container" AND resource.labels.namespace_name="prod"
logName="projects/my-proj/logs/run.googleapis.com%2Frequests" AND httpRequest.status>=500
```

See: https://cloud.google.com/logging/docs/view/logging-query-language
