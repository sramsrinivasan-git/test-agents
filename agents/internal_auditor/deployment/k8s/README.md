# Internal Auditor — GKE deployment

Deploys the Orchestrator as a long-running Pub/Sub subscriber pod
inside a GKE cluster. Triggers arrive as messages on a Pub/Sub topic
(published by Cloud Scheduler for cron audits, by humans / other
systems for ad-hoc); results are written to Cloud Logging keyed by
`run_id`.

Topology in the cluster:

```
                       Cloud Scheduler          gcloud pubsub publish
                            │                         │
                            ▼                         ▼
                   ┌──────────────────────────────────────┐
                   │  Pub/Sub topic                       │
                   │   internal-auditor-triggers          │
                   └─────────────────┬────────────────────┘
                                     │ subscription
                                     ▼
default namespace
└── Deployment: internal-auditor (Pub/Sub subscriber; long-running)
        │   KSA: internal-auditor
        │ claims one sandbox per specialist tool call (in agent-sandbox ns)
        ▼
agent-sandbox namespace   (deployed + owned separately; NOT by this guide)
├── SandboxWarmPool gcp-log-analyzer-warmpool-mcp
└── SandboxWarmPool gcp-cloud-asset-warmpool-mcp

Result lands in Cloud Logging: jsonPayload.run_id == "audit-..."
```

The MCP servers and their warm pools are deployed and owned separately
(out of scope for this guide). This guide only covers the orchestrator
itself + the cluster-side glue: the orchestrator's ServiceAccount, its
Deployment, the cross-namespace RBAC that lets it create SandboxClaims
in `agent-sandbox`, and the Pub/Sub trigger plumbing.

> Substitute throughout:
> - `PROJECT_ID` — GCP project hosting the GKE cluster + Pub/Sub topic.
> - `REGION` — Artifact Registry / cluster region (e.g. `us-central1`).
> - `CLUSTER` — your GKE cluster name.
> - `AR_REPO` — your existing Artifact Registry Docker repo name (e.g. `aaas-repo`).

---

## 1. Prereqs

- GKE cluster with **Workload Identity** enabled.
- GKE cluster with **Agent Sandbox** enabled (gVisor node pool + the
  Agent Sandbox controller). See `notes.md`.
- The CRDs `SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim` under
  `extensions.agents.x-k8s.io/v1beta1` should be present.
- `kubectl` configured against the cluster.
- Artifact Registry Docker repo already exists in your project (we
  don't create it here; ask your platform team if it doesn't).
- **Both MCP server warm pools already deployed** in the `agent-sandbox`
  namespace, named `gcp-log-analyzer-warmpool-mcp` and
  `gcp-cloud-asset-warmpool-mcp`. Confirm with
  `kubectl -n agent-sandbox get sandboxwarmpools`.
- Pub/Sub API enabled:
  `gcloud services enable pubsub.googleapis.com --project=$PROJECT_ID`

## 2. Pub/Sub topic + subscription (one-time)

> **Do this BEFORE step 5.** The orchestrator pod opens a streaming
> pull on the subscription as its first action; if the subscription
> doesn't exist, the pod crash-loops with a `NotFound` error.

Pub/Sub setup lives with the other one-time GCP storage setup in
[`../../gcp_setup/`](../../gcp_setup/). See
[`gcp_setup/DEPLOY.md` §4](../../gcp_setup/DEPLOY.md) for the Console
walkthrough and IAM details. One-shot script:

```bash
export PROJECT_ID=my-project
export GSA_EMAIL="internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com"
agents/internal_auditor/gcp_setup/create_pubsub.sh

# With DLQ for poison messages (recommended):
CREATE_DLQ=1 agents/internal_auditor/gcp_setup/create_pubsub.sh
```

The script enables the API, creates the topic + subscription
(`internal-auditor-triggers` / `internal-auditor-triggers-sub`,
ack-deadline 10 min), and grants the GSA `roles/pubsub.subscriber`
on the subscription. Idempotent — re-runs are safe.

Step 3 below covers creating `GSA_EMAIL` itself if you haven't yet;
in that case, do step 3 *first*, then this step.

## 3. Orchestrator service account (one-time)

```bash
gcloud iam service-accounts create internal-auditor \
  --project="$PROJECT_ID" \
  --display-name="Internal Auditor agent"

# Vertex AI for Gemini.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# (Pub/Sub subscriber on the trigger subscription is granted by step 2's
#  create_pubsub.sh; not repeated here.)

# Workload Identity binding: K8s SA `internal-auditor` in the `default`
# namespace impersonates the GSA.
gcloud iam service-accounts add-iam-policy-binding \
  "internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[default/internal-auditor]"

sed -i.bak "s/PROJECT_ID/$PROJECT_ID/g" \
  agents/internal_auditor/deployment/k8s/serviceaccount.yaml
```

## 4. Build + push the orchestrator image

```bash
ORCHESTRATOR_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/internal-auditor:0.1.0"
gcloud builds submit agents/internal_auditor --tag "$ORCHESTRATOR_IMAGE"

sed -i.bak "s|REPLACE_WITH_ARTIFACT_REGISTRY_IMAGE|$ORCHESTRATOR_IMAGE|" \
  agents/internal_auditor/deployment/k8s/deployment.yaml
```

## 5. Apply orchestrator manifests

The orchestrator runs in the `default` namespace; the cross-namespace
`rbac.yaml` (Role + RoleBinding in `agent-sandbox`) lets its SA create
SandboxClaims where the warm pools live.

```bash
# ConfigMap the Deployment reads GOOGLE_CLOUD_PROJECT from (same ns as the pod).
kubectl -n default create configmap gcp-config \
  --from-literal=project_id="$PROJECT_ID" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f agents/internal_auditor/deployment/k8s/serviceaccount.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/deployment.yaml

# RBAC: lets the orchestrator's SA (default/internal-auditor) create,
# get, and delete SandboxClaim resources in the agent-sandbox namespace.
# Requires you can create RBAC in agent-sandbox (cluster-admin or an
# equivalent grant in that namespace).
kubectl apply -f agents/internal_auditor/deployment/k8s/rbac.yaml
```

No `service.yaml` — the orchestrator has no HTTP surface.

---

### Profile A — smoke test without claiming warm pools

To validate the GKE + Pub/Sub plumbing without exercising the
SandboxClaim path (fast first smoke, or to isolate a problem to the
claim layer), deploy the orchestrator in `SANDBOX_MODE=local` pointing
at deliberately unreachable URLs. The specialists fail their MCP calls
fast, the orchestrator wraps each failure in its `findings` slot (per
its instruction) and the audit completes normally. Every layer this
repo builds is exercised except the claim + MCP calls themselves.

Patch the env block in `deployment.yaml` for this profile:

```yaml
- name: SANDBOX_MODE
  value: "local"                          # was "cluster"
- name: GCP_LOG_ANALYZER_MCP_URL
  value: "http://localhost:1/mcp"         # deliberately unreachable
- name: GCP_CLOUD_ASSET_MCP_URL
  value: "http://localhost:1/mcp"
```

You can also skip applying `rbac.yaml` for this profile — local mode
never creates SandboxClaim resources, so the RBAC isn't needed.

Revert both changes (and apply `rbac.yaml`) once you're ready to wire
in real warm pools.

---

## 6. Smoke-test by publishing a trigger

```bash
gcloud pubsub topics publish internal-auditor-triggers \
  --project="$PROJECT_ID" \
  --message='{"trigger_type":"on_demand","lookback_hours":1.0}'
```

Watch the orchestrator pull it and run:

```bash
kubectl -n default logs deployment/internal-auditor -f

# In another shell, watch claims fly while the audit runs (cluster-mode only):
kubectl -n agent-sandbox get sandboxclaims -w
```

The result is logged as a single structured line; pull it from Cloud Logging:

```bash
gcloud logging read \
  'resource.type=k8s_container
   AND resource.labels.namespace_name=default
   AND resource.labels.container_name=internal-auditor
   AND jsonPayload.run_id:"audit-"' \
  --project="$PROJECT_ID" \
  --limit=1 --format=json
```

## 7. Wire Cloud Scheduler for cron audits

```bash
gcloud scheduler jobs create pubsub internal-auditor-hourly \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 * * * *" \
  --topic=internal-auditor-triggers \
  --message-body='{"trigger_type":"scheduled","lookback_hours":1.0}'
```

`--schedule` is standard cron. The job publishes the same message shape
the orchestrator handles for ad-hoc audits.

## 8. Updating the orchestrator

```bash
gcloud builds submit agents/internal_auditor --tag "${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n default set image deployment/internal-auditor \
  internal-auditor="${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n default rollout status deployment/internal-auditor
```

MCP server updates: see their respective DEPLOY.md files.

## Notes

- **Vertex AI region** — `GOOGLE_CLOUD_LOCATION` in `deployment.yaml`
  defaults to `us-central1`. Change to where you have Gemini 3 Flash quota.
- **Concurrency** — `PUBSUB_MAX_CONCURRENT=1` means the pod processes
  audits serially. Raise it (e.g. `4`) to let one pod run up to N
  audits in parallel; each holds its own sandbox claims.
- **Backlog scaling** — KEDA can scale this Deployment on Pub/Sub
  subscription backlog. Not enabled by default; one pod handles
  hourly-cron load comfortably.
- **Liveness** — the pod ships a heartbeat file (`/tmp/alive`) updated
  per message and every 15s; the `exec` livenessProbe declares it
  stale at 90s and restarts the pod. Detects a deadlocked subscriber,
  not just a running process.
- **MCP auth** — orchestrator → MCP-server-pod traffic is unauthenticated
  today (in-cluster pod IP, no mTLS). Before production, run both inside
  a service mesh so the connections are mTLS-encrypted.
- **API version** — `rbac.yaml` grants on `extensions.agents.x-k8s.io`
  (sandboxclaims) and `agents.x-k8s.io` (sandboxes). If your installed
  controller serves a different version/group, adjust the `apiGroups`
  there and `SANDBOX_*` wiring accordingly.
- **Namespaces** — orchestrator + its SA live in `default`; warm pools,
  SandboxClaims, and the claim RBAC live in `agent-sandbox`. If either
  moves, update `deployment.yaml` (`SANDBOX_NAMESPACE`, the Deployment
  namespace), `rbac.yaml` (both objects' namespace + the subject), and
  the Workload Identity member in step 3.
