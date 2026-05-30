# gcp_cloud_asset

FastMCP server exposing the Google Cloud Asset API as a set of tools an MCP
client (e.g. Claude) can call to search, list, and analyze GCP assets and IAM
policies across projects, folders, and organizations.

## Layout

```
mcp_servers/gcp_cloud_asset/
├── pyproject.toml          # this package's deps + console script
├── README.md               # you are here
├── Dockerfile              # production image for Cloud Run
├── tests/                  # tests for this server
└── src/                    # the package contents (importable as `gcp_cloud_asset`)
    ├── __init__.py
    ├── server.py           # FastMCP entrypoint, registers every tool
    ├── common.py           # shared helpers (client, scope resolution, normalization)
    └── tools/              # one file per MCP tool
        ├── __init__.py     # exports ALL_TOOLS
        ├── search_resources.py
        ├── search_iam_policies.py
        ├── list_assets.py
        ├── analyze_iam_policy.py
        └── get_asset_history.py
```

The package name is `gcp_cloud_asset` (set in `pyproject.toml` via
`package-dir`), so imports look like:

```python
from gcp_cloud_asset.tools import search_resources
```

## Tools

- `search_resources(query?, asset_types?, scope?, project_id?, page_size?, order_by?)` —
  full-text search across GCP resources in a scope.
- `search_iam_policies(query, asset_types?, scope?, project_id?, page_size?, order_by?)` —
  full-text search across IAM policy bindings.
- `list_assets(asset_types?, scope?, project_id?, content_type?, snapshot_time?, page_size?)` —
  list assets with their full configuration or IAM policies, optionally at a past point-in-time.
- `analyze_iam_policy(resource?, identity?, roles?, permissions?, scope?, project_id?, ...)` —
  structured analysis of who has what access to a resource.
- `get_asset_history(asset_names, content_type?, hours?, start_time?, end_time?, scope?, project_id?)` —
  fetch the change history of specific assets over a time window (up to 35 days back).

## Install (from the workspace root)

```bash
uv sync                                    # installs all workspace members
# or, just this package:
uv pip install -e mcp_servers/gcp_cloud_asset
```

## Configure GCP

```bash
gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
```

The caller needs at minimum `roles/cloudasset.viewer` on the target scope.
For `analyze_iam_policy` you also need the Cloud Asset API enabled on the
project that hosts the service (`cloudasset.googleapis.com`).

## Run

```bash
uv run gcp-cloud-asset-mcp
# or
uv run python -m gcp_cloud_asset.server
```

## Test

```bash
uv run pytest mcp_servers/gcp_cloud_asset/tests/
```

## Adding a new tool

1. Create `src/tools/my_tool.py` with a single function and a detailed
   docstring (purpose, when-to-use, args, returns).
2. Import it and append to `ALL_TOOLS` in `src/tools/__init__.py`.
3. `server.py` registers it automatically on the next start.

## Asset type examples

```text
storage.googleapis.com/Bucket
compute.googleapis.com/Instance
container.googleapis.com/Cluster
iam.googleapis.com/ServiceAccount
cloudresourcemanager.googleapis.com/Project
sqladmin.googleapis.com/Instance
bigquery.googleapis.com/Dataset
```

See the full list: https://cloud.google.com/asset-inventory/docs/supported-asset-types
