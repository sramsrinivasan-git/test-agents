"""Tool functions exposed by the GCP log-analyzer MCP server.

Each module here defines one tool as a plain function. `server.py` is
responsible for registering them with the FastMCP instance, so the tools
themselves remain framework-agnostic and unit-testable.
"""

from .list_log_names import list_log_names
from .query_logs import query_logs
from .recent_errors import recent_errors
from .severity_histogram import severity_histogram
from .summarize_errors import summarize_errors
from .top_error_messages import top_error_messages

ALL_TOOLS = [
    query_logs,
    recent_errors,
    summarize_errors,
    severity_histogram,
    list_log_names,
    top_error_messages,
]

__all__ = [
    "ALL_TOOLS",
    "list_log_names",
    "query_logs",
    "recent_errors",
    "severity_histogram",
    "summarize_errors",
    "top_error_messages",
]
