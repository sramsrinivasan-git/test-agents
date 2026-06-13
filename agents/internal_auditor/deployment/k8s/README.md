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
  (see `notes` in the repo root for the cluster-creation walkthrough).
- The CRDs `SandboxTemplate`, `SandboxWarmPool`, `SandboxClaim` under
  `extensions.agents.x-k8s.io/v1beta1` should be present:
  `kubectl get crd | grep agents.x-k8s.io`. If your cluster still
  serves `v1alpha1`, adjust the apiVersion in `sandbox-*.yaml`.
- `kubectl` configured against the cluster.
- An Artifact Registry Docker repo
  (`gcloud artifacts repositories create AR_REPO --repository-format=docker --location=REGION`).
- Both MCP server images already pushed to that repo
  (`gcp-log-analyzer` and `gcp-cloud-asset` from `mcp_servers/*`).

## 2. Service accounts (one-time)

Create the Google Service Account that the orchestrator pod will
impersonate via Workload Identity, and grant Vertex AI access:

```bash
gcloud iam service-accounts create internal-auditor \
  --project="$PROJECT_ID" \
  --display-name="Internal Auditor agent"

# Vertex AI access for Gemini calls.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"

# Workload Identity binding: K8s SA in namespace `agents` can impersonate the GSA.
gcloud iam service-accounts add-iam-policy-binding \
  "internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${PROJECT_ID}.svc.id.goog[agents/internal-auditor]"
```

The MCP server sandboxes need their own GSA for the GCP APIs they
read (`roles/logging.viewer` for the log analyzer,
`roles/cloudasset.viewer` for the cloud asset server) — set this up
the same way and bind it to the sandbox pods via the template's
`serviceAccountName` if you go beyond unauth.

Then patch the annotation in `serviceaccount.yaml`:

```bash
sed -i.bak "s/PROJECT_ID/$PROJECT_ID/g" deployment/k8s/serviceaccount.yaml
```

## 3. Build + push images

From the repo root:

```bash
ORCHESTRATOR_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/internal-auditor:0.1.0"
LOG_ANALYZER_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/gcp-log-analyzer:0.1.0"
CLOUD_ASSET_IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/gcp-cloud-asset:0.1.0"

gcloud builds submit agents/internal_auditor       --tag "$ORCHESTRATOR_IMAGE"
gcloud builds submit mcp_servers/gcp_log_analyzer  --tag "$LOG_ANALYZER_IMAGE"
gcloud builds submit mcp_servers/gcp_cloud_asset   --tag "$CLOUD_ASSET_IMAGE"
```

Patch the manifests:

```bash
sed -i.bak "s|REPLACE_WITH_ARTIFACT_REGISTRY_IMAGE|$ORCHESTRATOR_IMAGE|" agents/internal_auditor/deployment/k8s/deployment.yaml
sed -i.bak "s|REPLACE_WITH_AR/mcp_servers/gcp-log-analyzer:0.1.0|$LOG_ANALYZER_IMAGE|" agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
sed -i.bak "s|REPLACE_WITH_AR/mcp_servers/gcp-cloud-asset:0.1.0|$CLOUD_ASSET_IMAGE|" agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml
```

## 4. Apply manifests

```bash
kubectl create namespace agents 2>/dev/null || true

# ConfigMap the Deployment + sandbox templates read GOOGLE_CLOUD_PROJECT from.
# Note: created in BOTH namespaces because the warm pool pods live in default.
kubectl -n agents  create configmap gcp-config --from-literal=project_id="$PROJECT_ID" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n default create configmap gcp-config --from-literal=project_id="$PROJECT_ID" --dry-run=client -o yaml | kubectl apply -f -

# Orchestrator workload identity + deployment + service.
kubectl apply -f agents/internal_auditor/deployment/k8s/serviceaccount.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/deployment.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/service.yaml

# Sandbox templates + warm pools (live in `default` by default).
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml

# RBAC: lets the orchestrator's K8s SA claim from the warm pools.
kubectl apply -f agents/internal_auditor/deployment/k8s/rbac.yaml
```

Verify the warm pools come up:

```bash
kubectl -n default get sandboxwarmpools
# Both should reach READY 2/2 within ~30s.

kubectl -n default get pods -l sandbox-type=mcp-server
# You should see 4 idle pods (2 per pool).
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

## 6. Updating

```bash
gcloud builds submit agents/internal_auditor --tag "${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n agents set image deployment/internal-auditor \
  internal-auditor="${ORCHESTRATOR_IMAGE%:*}:0.1.1"
kubectl -n agents rollout status deployment/internal-auditor
```

MCP server updates: rebuild + push the new image, then bump the
`image:` in the corresponding `sandbox-*.yaml` and re-apply. The
controller drains the warm pool and refills with pods running the new
image.

## Notes

- **Vertex AI region** — `GOOGLE_CLOUD_LOCATION` in `deployment.yaml`
  defaults to `us-central1`. Change it to the region where you have
  Gemini 3 Flash quota.
- **GKE Agent Sandbox** — sandbox pods land on gVisor nodes
  automatically because the templates set `runtimeClassName: gvisor`.
  Your cluster needs at least one node pool created with
  `--sandbox=type=gvisor` for them to schedule.
- **MCP auth** — the orchestrator → MCP-server pod traffic is
  unauthenticated today (in-cluster pod IP, no mTLS). Before
  production, run both inside a service mesh (Istio / Anthos Service
  Mesh) so the connections are mTLS-encrypted.
- **API version** — manifests use `extensions.agents.x-k8s.io/v1beta1`
  (current upstream). If your cluster controller still serves
  `v1alpha1`, change the four `apiVersion:` lines in `sandbox-*.yaml`
  and the two in `rbac.yaml` (it references `sandboxclaims`).
