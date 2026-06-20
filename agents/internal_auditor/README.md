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
releases it. The orchestrator itself runs as a long-running pod that
**subscribes to a Pub/Sub topic** for audit triggers; results land in
Cloud Logging keyed by `run_id`.

Not yet implemented (see `src/agent.py` header for the list):
Agent Behavior Evaluator, Policy Evaluator, Alert Dispatcher,
BigQuery/Firestore writes, ReAct scratchpad/replan.

Built on **Google ADK** with **Gemini 3 Flash**. Designed to run on
**GKE with Agent Sandbox enabled**.

## Layout

Shared, agent-agnostic runtime lives in the top-level `common/` package
(`common.sandbox`, `common.runner`, `common.pubsub`, `common.heartbeat`,
`common.ids`, `common.config`). This package holds only the audit-
specific pieces:

```
src/internal_auditor/
├── agent.py            orchestrator (root_agent); calls specialists as FunctionTools
├── log_analyzer.py     log analyzer specialist (claim → inner LLM → release)
├── asset_inspector.py  asset inspector specialist (same shape)
├── schemas.py          output JSON shapes (single source of truth)
├── config.py           audit-specific config (model, warm pools, project)
└── subscriber.py       Pub/Sub entrypoint: pull trigger → run root_agent → log result

tests/test_smoke.py          import + shape tests (no cluster, no Gemini)
Dockerfile + .dockerignore   container image (CMD: internal-auditor-subscriber)
deployment/k8s/              GKE manifests: orchestrator Deployment, warm pools,
                             RBAC for sandbox claims, walkthrough README
gcp_setup/                   one-time BQ + Firestore setup (used later)
deployment/terraform/        TF for BQ + Firestore (used later)
```

The claim lifecycle, the ADK run loop, the Pub/Sub subscriber loop, the
liveness heartbeat, and the `SANDBOX_*` / `MCP_SERVER_PORT` knobs all
come from `common/` and are reused by every agent.

## Run locally with `adk web`

For interactive development, `adk web` imports `root_agent` directly and
bypasses Pub/Sub entirely - the subscriber is a production-only entry
point. `SANDBOX_MODE=local` skips the cluster claim path and points each
specialist at a static MCP server URL.

Common setup (all variants):

```bash
uv sync                                       # from repo root
export GEMINI_MODEL=gemini-3-flash
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
kubectl -n default port-forward pod/<a-warmpool-pod> 18080:8080 &     # gcp-log-analyzer
kubectl -n default port-forward pod/<another-warmpool-pod> 18081:8080 &  # gcp-cloud-asset
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
when a Cloud Scheduler cron publishes the trigger, `on_demand` for ad-hoc
publishes — the workflow is the same either way.)

## Deploy to GKE

See [`deployment/k8s/README.md`](deployment/k8s/README.md). Quick summary:

1. Build + push the orchestrator image (MCP server images per their own DEPLOY.md).
2. Create the Pub/Sub topic + subscription (`internal-auditor-triggers`).
3. Apply `serviceaccount.yaml`, `deployment.yaml`, and `rbac.yaml`.
4. Apply the sandbox manifests (`sandbox-log-analyzer.yaml`, `sandbox-cloud-asset.yaml`).
5. Wire Cloud Scheduler to publish to the topic on a cron.
6. Ad-hoc audits: `gcloud pubsub topics publish ...`.

## Tests

```bash
uv run --all-packages --with pytest python -m pytest agents/internal_auditor/tests
```
