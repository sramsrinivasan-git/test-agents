# Internal Auditor — GKE deployment

Deploys the Orchestrator as a single FastAPI service inside a GKE
cluster. The orchestrator's specialist tools claim sandboxed MCP server
pods from per-server warm pools at run time.

Topology in the cluster:

```
agents namespace
└── Deployment: internal-auditor (FastAPI; long-running)
        │
        │ claims one sandbox per specialist tool call
        ▼
default namespace (or wherever the warm pools live)
├── SandboxWarmPool gcp-log-analyzer-warmpool  (2 idle pods)
└── SandboxWarmPool gcp-cloud-asset-warmpool   (2 idle pods)
```

The MCP server warm pools have their own per-server deploy guides
(image build, GSA, Workload Identity binding, per-server IAM grants):

- [`mcp_servers/gcp_log_analyzer/DEPLOY.md`](../../../../mcp_servers/gcp_log_analyzer/DEPLOY.md)
- [`mcp_servers/gcp_cloud_asset/DEPLOY.md`](../../../../mcp_servers/gcp_cloud_asset/DEPLOY.md)

**This** guide only covers the orchestrator itself + the cluster-side
glue (RBAC for claims, ConfigMap, Service).

> Substitute throughout:
> - `PROJECT_ID` — GCP project hosting the GKE cluster.
> - `REGION` — Artifact Registry / cluster region (e.g. `us-central1`).
> - `CLUSTER` — your GKE cluster name.
> - `AR_REPO` — Artifact Registry Docker repo (e.g. `agents`).

---

## 1. Prereqs

- GKE cluster with **Workload Identity** enabled (the orchestrator
  pod needs to call Vertex AI without a static key).
- GKE cluster with **Agent Sandbox** enabled. The cluster must have a
  gVisor-sandbox node pool and the Agent Sandbox controller installed
  (see `notes.md` in the repo root for the cluster-creation walkthrough).
- The CRDs `SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim` under
  `extensions.agents.x-k8s.io/v1beta1` should be present:
  `kubectl get crd | grep agents.x-k8s.io`. If your cluster still
  serves `v1alpha1`, adjust the apiVersion in `sandbox-*.yaml` and
  `rbac.yaml`.
- `kubectl` configured against the cluster.
- An Artifact Registry Docker repo
  (`gcloud artifacts repositories create AR_REPO --repository-format=docker --location=REGION`).
- **Both MCP server warm pools already deployed** by following the per-server
  DEPLOY.md guides linked above. After those are done, `kubectl -n default
  get sandboxwarmpools` should show 2 pools at `READY 2/2`.

## 2. Orchestrator service account (one-time)

The orchestrator pod needs a Google Service Account it can impersonate
via Workload Identity to call Vertex AI.

```bash
gcloud iam service-accounts create internal-auditor \
  --project="$PROJECT_ID" \
  --display-name="Internal Auditor agent"

# Vertex AI access for Gemini calls.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Workload Identity binding: K8s SA in namespace `agents` impersonates the GSA.
gcloud iam service-accounts add-iam-policy-binding \
  "internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[agents/internal-auditor]"
```

Patch the annotation in `serviceaccount.yaml`:

```bash
sed -i.bak "s/PROJECT_ID/$PROJECT_ID/g" agents/internal_auditor/deployment/k8s/serviceaccount.yaml
```

## 3. Build + push the orchestrator image

```bash
ORCHESTRATOR_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/internal-auditor:0.1.0"
gcloud builds submit agents/internal_auditor --tag "$ORCHESTRATOR_IMAGE"

sed -i.bak "s|REPLACE_WITH_ARTIFACT_REGISTRY_IMAGE|$ORCHESTRATOR_IMAGE|" \
  agents/internal_auditor/deployment/k8s/deployment.yaml
```

## 4. Apply orchestrator manifests

```bash
kubectl create namespace agents 2>/dev/null || true

# ConfigMap the Deployment reads GOOGLE_CLOUD_PROJECT from.
# (The same key is also referenced by the sandbox templates in `default`,
# created by step 4 of each MCP server's DEPLOY.md.)
kubectl -n agents create configmap gcp-config \
  --from-literal=project_id="$PROJECT_ID" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f agents/internal_auditor/deployment/k8s/serviceaccount.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/deployment.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/service.yaml

# RBAC: lets the orchestrator's K8s SA claim/get/delete SandboxClaim
# resources in the namespace the warm pools live in.
kubectl apply -f agents/internal_auditor/deployment/k8s/rbac.yaml
```

## 5. Smoke-test from inside the cluster

```bash
kubectl -n agents port-forward svc/internal-auditor 8080:8080 &

curl -sS http://localhost:8080/healthz
# -> {"status":"ok"}

curl -sS -X POST http://localhost:8080/audit \
  -H 'Content-Type: application/json' \
  -d '{"trigger_type":"on_demand","lookback_hours":1.0}'
# -> {"run_id":"audit-...", "response":"{ ...orchestrator JSON... }"}
```

Watch claims fly while the audit is running:

```bash
kubectl -n default get sandboxclaims -w
```

## 6. Updating the orchestrator

```bash
gcloud builds submit agents/internal_auditor --tag "${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n agents set image deployment/internal-auditor \
  internal-auditor="${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n agents rollout status deployment/internal-auditor
```

MCP server updates are documented in their own DEPLOY.md files; bumping
the image in `sandbox-*.yaml` and re-applying drains/refills the warm pool.

## Notes

- **Vertex AI region** — `GOOGLE_CLOUD_LOCATION` in `deployment.yaml`
  defaults to `us-central1`. Change it to the region where you have
  Gemini 3 Flash quota.
- **MCP auth** — orchestrator → MCP-server-pod traffic is unauthenticated
  today (in-cluster pod IP, no mTLS). Before production, run both inside
  a service mesh (Istio / Anthos Service Mesh) so the connections are
  mTLS-encrypted.
- **API version** — manifests use `extensions.agents.x-k8s.io/v1beta1`
  (current upstream). If your cluster controller still serves `v1alpha1`,
  change the apiVersion lines in `sandbox-*.yaml` and `rbac.yaml`.
