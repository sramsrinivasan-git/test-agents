# GCP Log Analyzer MCP Server

A [FastMCP](https://github.com/jlowin/fastmcp) server that exposes Google Cloud Logging
as a set of tools an MCP client (e.g. Claude) can call to query and summarize logs.

## Layout

```
mcp_servers/
  gcp_log_analyzer/
    server.py          # FastMCP entrypoint, registers every tool
    common.py          # shared helpers (client, project resolution, filters)
    tools/
      __init__.py      # exports ALL_TOOLS
      query_logs.py
      recent_errors.py
      summarize_errors.py
      severity_histogram.py
      list_log_names.py
      top_error_messages.py
```

Each tool is a plain function in its own module; `server.py` registers them with
the FastMCP instance. This keeps tools framework-agnostic and unit-testable.

## Tools

- `query_logs(filter, project_id?, page_size?, order_by?)` — run a raw Cloud Logging
  advanced filter and return matching entries.
- `recent_errors(hours, project_id?, min_severity?, resource_type?, page_size?)` —
  fetch recent entries at or above a given severity.
- `summarize_errors(hours, project_id?, min_severity?, top_n?, group_by?)` —
  bucket recent errors by `resource_type`, `log_name`, or `severity`.
- `severity_histogram(hours, project_id?, resource_type?)` — count entries by severity.
- `top_error_messages(hours, project_id?, min_severity?, top_n?)` — most frequent error
  message strings.
- `list_log_names(project_id?)` — enumerate log names in the project.

## Setup

```bash
pip install -e .
export GOOGLE_CLOUD_PROJECT=your-project-id
gcloud auth application-default login
```

The service account / user needs the `roles/logging.viewer` role
(or `roles/logging.privateLogViewer` for data-access logs).

## Run

```bash
python -m mcp_servers.gcp_log_analyzer.server
# or, after `pip install -e .`:
gcp-log-analyzer-mcp
```

Configure your MCP client to launch this process via stdio.

## Adding a new tool

1. Create `mcp_servers/gcp_log_analyzer/tools/my_tool.py` with a single function
   and a detailed docstring (purpose, when-to-use, args, returns).
2. Import and append it to `ALL_TOOLS` in `tools/__init__.py`.
3. `server.py` registers it automatically.

## Filter examples

```text
severity>=ERROR AND resource.type="cloud_run_revision"
resource.type="k8s_container" AND resource.labels.namespace_name="prod"
logName="projects/my-proj/logs/run.googleapis.com%2Frequests" AND httpRequest.status>=500
```

See: https://cloud.google.com/logging/docs/view/logging-query-language
