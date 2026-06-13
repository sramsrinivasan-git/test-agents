# Internal Auditor — agent

Implements three of the agents from [`plan.md`](../../plan.md):

- **Orchestrator** — root agent; receives audit triggers and calls the
  specialists below in parallel as `FunctionTool`s.
- **Log Analyzer** — fetches Cloud Logging audit events via the
  `gcp-log-analyzer` MCP server.
- **Asset Inspector** — snapshots GCP resource state + IAM bindings via
  the `gcp-cloud-asset` MCP server.

Each specialist tool call **claims a fresh sandboxed MCP server pod**
from a GKE Agent Sandbox warm pool, uses it for that single call, and
releases it. The orchestrator itself runs as a regular long-running pod.

Not yet implemented (see `src/agent.py` header for the list):
Agent Behavior Evaluator, Policy Evaluator, Alert Dispatcher,
BigQuery/Firestore writes, ReAct scratchpad/replan.

Built on **Google ADK** with **Gemini 3 Flash**. Designed to run on
**GKE with Agent Sandbox enabled**.

## Layout

```
src/internal_auditor/
├── agent.py            orchestrator (root_agent); calls specialists as FunctionTools
├── log_analyzer.py     log analyzer specialist (claim → inner LLM → release)
├── asset_inspector.py  asset inspector specialist (same shape)
├── sandbox.py          SandboxClaim lifecycle helper (k8s-agent-sandbox client)
├── _inner_run.py       runs a one-shot inner LlmAgent and returns its final text
├── config.py           env-driven config (SANDBOX_MODE, warm pools, model, ...)
└── server.py           FastAPI entry (internal-auditor-server)

tests/test_smoke.py          import + shape tests (no cluster, no Gemini)
Dockerfile + .dockerignore   container image
deployment/k8s/              GKE manifests: orchestrator Deployment, warm pools,
                             RBAC for sandbox claims, walkthrough README
gcp_setup/                   one-time BQ + Firestore setup (used later)
deployment/terraform/        TF for BQ + Firestore (used later)
```

## Run locally with `adk web`

The full path (real `SandboxClaim` against a real cluster) requires
kube access. For local development you can run in `SANDBOX_MODE=local`
which skips claims and connects to a static MCP server URL — point it
at a port-forwarded MCP server pod.

```bash
uv sync                                       # from repo root
export GEMINI_MODEL=gemini-3-flash
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION=us-central1

# Local-mode wiring: skip SandboxClaim, talk to port-forwarded MCP pods.
export SANDBOX_MODE=local
kubectl -n default port-forward pod/<a-warmpool-pod> 18080:8080 &     # gcp-log-analyzer
kubectl -n default port-forward pod/<another-warmpool-pod> 18081:8080 &  # gcp-cloud-asset
export GCP_LOG_ANALYZER_MCP_URL=http://localhost:18080/mcp
export GCP_CLOUD_ASSET_MCP_URL=http://localhost:18081/mcp

# Interactive UI:
cd agents/internal_auditor/src   # adk web auto-discovers packages in cwd
adk web                          # opens http://localhost:8000
```

In the ADK web UI, select `internal_auditor` from the agent picker and
send a message like:
> `trigger_type=on_demand lookback_hours=1 run_id=audit-local-1`

You'll see the orchestrator fan out to `log_analyzer` + `asset_inspector`
in parallel and return the merged JSON. (`trigger_type` is `scheduled`
when a Cloud Scheduler cron fires the run, `on_demand` for everything
else — the workflow is the same either way.)

## Deploy to GKE

See [`deployment/k8s/README.md`](deployment/k8s/README.md). Quick summary:

1. Build + push three images (orchestrator + both MCP servers).
2. Apply `serviceaccount.yaml`, `deployment.yaml`, `service.yaml` for
   the orchestrator.
3. Apply `sandbox-log-analyzer.yaml` and `sandbox-cloud-asset.yaml` —
   these create the `SandboxTemplate` + `SandboxWarmPool` per server type.
4. Apply `rbac.yaml` so the orchestrator's K8s ServiceAccount can
   create / get / delete `SandboxClaim` resources.

## Tests

```bash
uv run pytest agents/internal_auditor/tests
```
