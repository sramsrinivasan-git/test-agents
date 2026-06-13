# Internal Auditor — agent (POC)

POC build of three of the agents from [`plan.md`](../../plan.md):

- **Orchestrator** — root agent; receives batch triggers and calls the
  specialists below in parallel as `AgentTool`s.
- **Log Analyzer** — fetches Cloud Logging audit events via the
  `gcp-log-analyzer` MCP server.
- **Asset Inspector** — snapshots GCP resource state + IAM bindings via
  the `gcp-cloud-asset` MCP server.

Out of scope here (per the POC carve-out — see `src/agent.py` header for
the list): Agent Behavior Evaluator, Policy Evaluator, Alert Dispatcher,
BigQuery/Firestore writes, ReAct scratchpad/replan.

Built on **Google ADK** with **Gemini 3 Flash**. Designed to run as a
FastAPI service on **GKE** alongside the MCP server it talks to.

## Layout

```
src/internal_auditor/
├── agent.py            orchestrator (root_agent); calls specialists as AgentTools
├── log_analyzer.py     log analyzer specialist + MCPToolset
├── asset_inspector.py  asset inspector specialist + MCPToolset
├── config.py           env-driven config
├── main.py             CLI entry (internal-auditor)
└── server.py           FastAPI entry (internal-auditor-server)

tests/test_smoke.py          import-only smoke tests
Dockerfile + .dockerignore   container image
deployment/k8s/              GKE manifests + walkthrough
gcp_setup/                   one-time BQ + Firestore setup (used later)
deployment/terraform/        TF for BQ + Firestore (used later)
```

## Run locally

```bash
uv sync                                       # from repo root
export GEMINI_MODEL=gemini-3-flash
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION=us-central1

# Point at port-forwarded MCP servers if you don't have them in-cluster:
kubectl -n mcp-servers port-forward svc/gcp-log-analyzer-mcp 18080:8080 &
kubectl -n mcp-servers port-forward svc/gcp-cloud-asset-mcp  18081:8080 &
export GCP_LOG_ANALYZER_MCP_URL=http://localhost:18080/mcp
export GCP_CLOUD_ASSET_MCP_URL=http://localhost:18081/mcp

# One-shot CLI run:
internal-auditor --lookback-hours 1

# Or the HTTP server:
internal-auditor-server
curl -s -X POST localhost:8080/audit \
  -H 'Content-Type: application/json' \
  -d '{"trigger_type":"batch","lookback_hours":1.0}'
```

## Deploy to GKE

See [`deployment/k8s/README.md`](deployment/k8s/README.md).

## Tests

```bash
uv run pytest agents/internal_auditor/tests
```
