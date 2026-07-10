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
releases it. The orchestrator is served by **ADK's own `adk api_server`**
(the fleet-standard entry point) and invoked over its REST API — by Cloud
Scheduler on a cron and by ad-hoc / other-agent callers.

New here? [`ARCHITECTURE.md`](ARCHITECTURE.md) explains how everything
connects in plain language (with diagrams and an audit-firm analogy).

Not yet implemented (see `src/agent.py` header for the list):
Agent Behavior Evaluator, Policy Evaluator, Alert Dispatcher,
BigQuery/Firestore writes, ReAct scratchpad/replan.

Built on **Google ADK** with **Gemini** (Pro orchestrator / Flash
specialists). Runs on **GKE with Agent Sandbox enabled**.

## Layout

Shared, agent-agnostic runtime lives in the top-level `common/` package
(`common.sandbox`, `common.runner`, `common.config`). This package holds
only the audit-specific pieces:

```
src/internal_auditor/
├── agent.py            orchestrator (root_agent); calls specialists as FunctionTools
├── log_analyzer.py     log analyzer specialist (claim → inner LLM → release)
├── asset_inspector.py  asset inspector specialist (same shape)
├── schemas.py          output JSON shapes (single source of truth)
└── config.py           audit-specific config (models, warm pools, project)

__init__.py                  re-exports root_agent so `adk api_server` discovers it
tests/test_smoke.py          import + shape tests (no cluster, no Gemini)
gcp_setup/                   one-time GCP setup (BQ + Firestore; used by future Policy Agent)
deployment/terraform/        TF for BQ + Firestore (used later)
```

There is **no server / Dockerfile in this package**: the agent is served
by `adk api_server` and built by the shared root `Dockerfile.agent` +
`cloudbuild.yaml`, deployed by the `infra/modules/agent-spoke` Terraform
module. The claim lifecycle, the ADK run loop, and the `SANDBOX_*` /
`MCP_SERVER_PORT` knobs come from `common/` and are reused by every agent.

## Run locally with `adk web`

`adk web` imports `root_agent` directly. `SANDBOX_MODE=local` skips the
cluster claim path and points each specialist at a static MCP server URL.

```bash
uv sync                                       # from repo root
# Models default to gemini-pro-latest / gemini-flash-latest (PRO_MODEL /
# FLASH_MODEL); override only if needed.
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION=global
export SANDBOX_MODE=local
```

Then pick a variant for the MCP URLs:

**Variant 1 - no MCP at all (fastest smoke test).** Point at unreachable
URLs; specialists fail fast, orchestrator wraps the errors in `findings`
and returns the merged JSON.

```bash
export GCP_LOG_ANALYZER_MCP_URL=http://localhost:1/mcp
export GCP_CLOUD_ASSET_MCP_URL=http://localhost:1/mcp
```

**Variant 2 - port-forward to MCP pods.** Talk to real MCP servers.

```bash
kubectl -n agent-sandbox port-forward pod/<a-warmpool-pod> 18080:8080 &     # gcp-log-analyzer
kubectl -n agent-sandbox port-forward pod/<another-warmpool-pod> 18081:8080 &  # gcp-cloud-asset
export GCP_LOG_ANALYZER_MCP_URL=http://localhost:18080/mcp
export GCP_CLOUD_ASSET_MCP_URL=http://localhost:18081/mcp
```

Then launch the UI:

```bash
cd agents/internal_auditor/src   # adk web auto-discovers packages in cwd
adk web                          # opens http://localhost:8000
```

In the UI, pick `internal_auditor` and send a message like:
> `trigger_type=on_demand lookback_hours=1 run_id=audit-local-1`

The orchestrator reads `trigger_type` / `lookback_hours` / `run_id` from
the message text, fans out to both specialists, and returns the merged
JSON.

## Deploy to GKE

Deployment is done by the **`infra/modules/agent-spoke`** Terraform
module (build image → GSA + Workload Identity → ClusterRole for
SandboxClaims → Deployment running `adk api_server` → ClusterIP Service).
This agent package ships only code; the module + shared root
`Dockerfile.agent` / `cloudbuild.yaml` do the rest.

Invoke the module for this agent roughly as:

```hcl
module "internal_auditor" {
  source     = "../../modules/agent-spoke"
  agent_name = "internal_auditor"
  project_id = var.project_id
  namespace  = "default"

  # MCP wiring is agent-specific -> passed via env_vars (the module is
  # MCP-agnostic). This agent claims from TWO warm pools in agent-sandbox.
  env_vars = {
    SANDBOX_MODE              = "cluster"
    MCP_NAMESPACE             = "agent-sandbox"
    GCP_LOG_ANALYZER_WARMPOOL = "gcp-log-analyzer-warmpool-mcp"
    GCP_CLOUD_ASSET_WARMPOOL  = "gcp-cloud-asset-warmpool-mcp"
  }
}
```

The module injects the platform-standard vars itself (`PRO_MODEL`,
`FLASH_MODEL`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
`GOOGLE_GENAI_USE_VERTEXAI`). BQ/Firestore for the future Policy Agent
are set up separately — see [`gcp_setup/DEPLOY.md`](gcp_setup/DEPLOY.md).

### Calling the deployed agent (ADK REST)

`adk api_server` exposes ADK's standard API. Create a session, then `/run`:

```bash
BASE=http://internal-auditor-agent-svc.default.svc.cluster.local:80
curl -sS -X POST $BASE/apps/internal_auditor/users/scheduler/sessions/$(uuidgen)  # create session
curl -sS -X POST $BASE/run -H 'Content-Type: application/json' -d '{
  "app_name": "internal_auditor",
  "user_id": "scheduler",
  "session_id": "<the session id>",
  "new_message": {"role": "user",
    "parts": [{"text": "trigger_type=scheduled lookback_hours=24"}]}
}'
```

Cloud Scheduler (HTTP target) and other agents call the same endpoints.
MCP servers + their warm pools are deployed/owned separately.

## Tests

```bash
uv run --all-packages --with pytest python -m pytest agents/internal_auditor/tests
```
