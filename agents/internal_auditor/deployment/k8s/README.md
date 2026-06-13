# Internal Auditor — GKE deployment

Deploys the Orchestrator + Log Analyzer agents as a single FastAPI
service inside a GKE cluster, alongside the `gcp-log-analyzer` MCP
server (which must already be running in the cluster — typically under
the `mcp-servers` namespace).

> Substitute throughout:
> - `PROJECT_ID` — GCP project hosting the GKE cluster.
> - `REGION` — Artifact Registry / cluster region (e.g. `us-central1`).
> - `CLUSTER` — your GKE cluster name.
> - `AR_REPO` — Artifact Registry Docker repo (e.g. `agents`).

---

## 1. Prereqs

- GKE cluster with **Workload Identity** enabled (required so the
  agent can call Vertex AI without a static key).
- The `gcp-log-analyzer` MCP server already running and reachable at
  `http://gcp-log-analyzer-mcp.mcp-servers.svc.cluster.local:8080/mcp`
  (or update the env var in `deployment.yaml` to match your layout).
- `kubectl` configured against the cluster.
- An Artifact Registry Docker repo (`gcloud artifacts repositories create AR_REPO --repository-format=docker --location=REGION`).

## 2. Service accounts (one-time)

Create the Google Service Account that the pod will impersonate via
Workload Identity, and grant it Vertex AI access:

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

Then sed the annotation in `serviceaccount.yaml`:

```bash
sed -i.bak "s/PROJECT_ID/$PROJECT_ID/g" deployment/k8s/serviceaccount.yaml
```

## 3. Build + push the image

From the agent root (`agents/internal_auditor/`):

```bash
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/internal-auditor:0.1.0"

gcloud builds submit --tag "$IMAGE" .
# or, if you prefer local builds:
#   docker build -t "$IMAGE" .
#   docker push "$IMAGE"
```

Then patch `deployment.yaml`:

```bash
sed -i.bak "s|REPLACE_WITH_ARTIFACT_REGISTRY_IMAGE|$IMAGE|" deployment/k8s/deployment.yaml
```

## 4. Apply manifests

```bash
kubectl create namespace agents 2>/dev/null || true

# ConfigMap the Deployment reads GOOGLE_CLOUD_PROJECT from.
kubectl -n agents create configmap gcp-config \
  --from-literal=project_id="$PROJECT_ID" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f deployment/k8s/serviceaccount.yaml
kubectl apply -f deployment/k8s/deployment.yaml
kubectl apply -f deployment/k8s/service.yaml
```

## 5. Smoke-test from inside the cluster

```bash
kubectl -n agents port-forward svc/internal-auditor 8080:8080 &

curl -sS http://localhost:8080/healthz
# -> {"status":"ok"}

curl -sS -X POST http://localhost:8080/audit \
  -H 'Content-Type: application/json' \
  -d '{"trigger_type":"batch","lookback_hours":1.0}'
# -> {"run_id":"audit-...", "response":"{ ...orchestrator JSON... }"}
```

## 6. Updating

```bash
gcloud builds submit --tag "${IMAGE%:*}:0.1.1" .
kubectl -n agents set image deployment/internal-auditor \
  internal-auditor="${IMAGE%:*}:0.1.1"
kubectl -n agents rollout status deployment/internal-auditor
```

## Notes

- **Vertex AI region** — `GOOGLE_CLOUD_LOCATION` in `deployment.yaml`
  defaults to `us-central1`. Change it to the region where you have
  Gemini 3 Flash quota.
- **GKE Agent Sandbox** — when you enable Agent Sandbox on the
  cluster, this Deployment will be scheduled into a sandboxed node pool
  automatically (no manifest change required), giving the agent its own
  gVisor-isolated runtime. The Service DNS name stays the same, so the
  MCP server URL keeps working.
- **MCP auth** — the connection to the in-cluster MCP server is
  unauthenticated today. When you move past POC, run both services
  inside a service mesh (Istio / Anthos Service Mesh) or wrap the MCP
  server with mTLS via the GKE Gateway API.
