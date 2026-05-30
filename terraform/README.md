# terraform/

Source of truth for the GCP resources that back the `gcp-log-analyzer`
MCP server deployment.

- **`schema.py`** — declarative dataclass description of every resource
  (APIs, service account, IAM bindings, Cloud Run service, invokers).
  Framework-agnostic; can be rendered to Terraform HCL, Pulumi, or
  gcloud scripts later.
- **`GCP_UI_SETUP.md`** — click-by-click walkthrough for creating the
  same resources through the GCP Cloud Console UI. Section numbers map
  1:1 to the resource blocks in `schema.py`.

For the original CLI-driven path see
[`../mcp_servers/gcp_log_analyzer/DEPLOY.md`](../mcp_servers/gcp_log_analyzer/DEPLOY.md).
