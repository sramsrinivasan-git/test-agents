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
releases it. The orchestrator itself runs as a long-running **FastAPI
service** (`POST /audit`) — triggered by Cloud Scheduler on a cron and
by ad-hoc / agent callers — and returns the merged audit JSON in the
HTTP response.

New here? [`ARCHITECTURE.md`](ARCHITECTURE.md) explains how everything
connects in plain language (with diagrams and an audit-firm analogy).

Not yet implemented (see `src/agent.py` header for the list):
Agent Behavior Evaluator, Policy Evaluator, Alert Dispatcher,
BigQuery/Firestore writes, ReAct scratchpad/replan.

Built on **Google ADK** with **Gemini 3 Flash**. Designed to run on
**GKE with Agent Sandbox enabled**.

## Layout

Shared, agent-agnostic runtime lives in the top-level `common/` package
(`common.sandbox`, `common.runner`, `common.serving`, `common.config`).
This package holds only the audit-specific pieces:

```
src/internal_auditor/
├── agent.py            orchestrator (root_agent); calls specialists as FunctionTools
├── log_analyzer.py     log analyzer specialist (claim → inner LLM → release)
├── asset_inspector.py  asset inspector specialist (same shape)
├── schemas.py          output JSON shapes (single source of truth)
├── config.py           audit-specific config (model, warm pools, project)
└── server.py           FastAPI entry: POST /audit → run root_agent → return JSON

tests/test_smoke.py          import + shape tests (no cluster, no Gemini)
Dockerfile + .dockerignore   container image (CMD: internal-auditor-server)
gcp_setup/                   one-time GCP setup (BQ + Firestore; used by future Policy Agent)
deployment/terraform/        TF for BQ + Firestore (used later)
```

The orchestrator's GKE deployment (Deployment, ServiceAccount + Workload
Identity, the ClusterIP Service, and the cross-namespace SandboxClaim
RBAC) is provisioned by a separate Terraform module owned by the platform
team — this repo does not ship those manifests.

The claim lifecycle, the ADK run loop, the FastAPI app + `/healthz`, and
the `SANDBOX_*` / `MCP_SERVER_PORT` knobs all come from `common/` and are
reused by every agent.

## Run locally with `adk web`

For interactive development, `adk web` imports `root_agent` directly and
bypasses the FastAPI server entirely - `server.py` is a production entry
point. `SANDBOX_MODE=local` skips the cluster claim path and points each
specialist at a static MCP server URL.

Common setup (all variants):

```bash
uv sync                                       # from repo root
# Model defaults live in internal_auditor.config (ORCHESTRATOR_MODEL=pro,
# SPECIALIST_MODEL=flash). Only export overrides if you want to change
# them per-environment.
export GOOGLE_CLOUD_PROJECT=my-project
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_LOCATION=us-central1
export SANDBOX_MODE=local
```

Then pick a variant for the MCP URLs:

**Variant 1 - no MCP at all (fastest smoke test).** Point at unreachable
URLs; specialists fail fast, orchestrator wraps the errors in `findings`
and returns the merged JSON. Verifies the agent loop without any MCP
infrastructure.

```bash
export GCP_LOG_ANALYZER_MCP_URL=http://localhost:1/mcp
export GCP_CLOUD_ASSET_MCP_URL=http://localhost:1/mcp
```

**Variant 2 - port-forward to MCP pods.** Talk to real MCP servers
running in a cluster (skip claim semantics).

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

In the ADK web UI, select `internal_auditor` from the agent picker and
send a message like:
> `trigger_type=on_demand lookback_hours=1 run_id=audit-local-1`

You'll see the orchestrator fan out to `log_analyzer` + `asset_inspector`
in parallel and return the merged JSON. (`trigger_type` is `scheduled`
when a Cloud Scheduler cron fires `POST /audit`, `on_demand` for ad-hoc
callers — the workflow is the same either way.)

## Deploy to GKE

The orchestrator's GKE workload — Deployment, ServiceAccount + Workload
Identity, the **ClusterIP Service**, and the cross-namespace SandboxClaim
RBAC — is provisioned by a **separate Terraform module owned by the
platform team**, not by this repo. The orchestrator runs in the `default`
namespace and claims from the warm pools in `agent-sandbox`.

What this repo is responsible for, before/around that Terraform deploy:

1. **GCP setup (one-time):** the orchestrator GSA + `roles/aiplatform.user`
   (Gemini), plus BQ/Firestore for the future Policy Agent. See
   [`gcp_setup/DEPLOY.md`](gcp_setup/DEPLOY.md). No Pub/Sub — triggering
   is HTTP.
2. **Build + push** the orchestrator image to your Artifact Registry repo
   (the Terraform deploy references this image).
3. **Runtime config** the Terraform must set on the pod: `SANDBOX_MODE=cluster`,
   `SANDBOX_NAMESPACE=agent-sandbox`, the two `GCP_*_WARMPOOL` names, and
   the Vertex AI envs (`GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`,
   `GOOGLE_GENAI_USE_VERTEXAI`). These match the defaults in `config.py` /
   `common.config`; share them with whoever owns the module. The pod
   listens on `:8080` (`/healthz` for the probe, `/audit` for triggers) —
   expose it as a **ClusterIP** Service (in-cluster only; no external LB
   in the request path, so no LB timeout).
4. **Triggers:** point **Cloud Scheduler** at the Service with an HTTP
   target hitting `POST /audit` on a cron; ad-hoc / other agents call the
   same endpoint in-cluster:
   ```bash
   curl -sS -X POST http://internal-auditor.default.svc.cluster.local:8080/audit \
     -H 'Content-Type: application/json' \
     -d '{"trigger_type":"on_demand","lookback_hours":1.0}'
   ```

(MCP servers + their warm pools are deployed/owned separately too — not
by this repo.)

## Tests

```bash
uv run --all-packages --with pytest python -m pytest agents/internal_auditor/tests
```
