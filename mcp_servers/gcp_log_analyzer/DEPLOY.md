# Deploying gcp-log-analyzer to GKE (as a sandboxed warm-pool MCP server)

This server runs as **pre-warmed gVisor-sandboxed pods inside a GKE
cluster**, managed by the GKE Agent Sandbox controller's
`SandboxWarmPool`. The Internal Auditor orchestrator claims one idle
pod per specialist tool call, talks to it over MCP, and releases it.

The deployment artifact is therefore an **Artifact Registry image**,
not a Cloud Run service. The actual `SandboxTemplate` + `SandboxWarmPool`
manifests live alongside the orchestrator in
[`agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml`](../../agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml).
This doc covers what's specific to **this MCP server**: building the
image, the GSA + Workload Identity binding, and the per-server IAM
grants the sandboxed pods need to read Cloud Logging.

## Pick your variables

```bash
# GCP project hosting the GKE cluster + Artifact Registry.
export HOST_PROJECT=my-host-project

# Project whose LOGS the server will analyze. Often the same as
# HOST_PROJECT; can be different (cross-project read).
export LOGS_PROJECT=my-logs-project

# AR repo + region.
export REGION=us-central1
export AR_REPO=agents
export IMAGE_TAG=0.1.0
export IMAGE="${REGION}-docker.pkg.dev/${HOST_PROJECT}/${AR_REPO}/gcp-log-analyzer:${IMAGE_TAG}"

# Identities. The GSA holds GCP IAM; the KSA is mounted into the
# sandbox pods and is bound to the GSA via Workload Identity.
export GSA_NAME=gcp-log-analyzer-mcp
export GSA_EMAIL="${GSA_NAME}@${HOST_PROJECT}.iam.gserviceaccount.com"
export KSA_NAME=gcp-log-analyzer-mcp
export NAMESPACE=default              # where the warm pool lives
```

## 1. Enable required APIs (one-time, in HOST_PROJECT)

GKE + per-server APIs the sandbox pods will need:

```bash
gcloud services enable \
  container.googleapis.com \
  iamcredentials.googleapis.com \
  logging.googleapis.com \
  --project="$HOST_PROJECT"
```

(Artifact Registry + Cloud Build APIs are enabled by the AR setup in
step 2.)

## 2. Artifact Registry Docker repo (one-time, project-wide)

The `$AR_REPO` Docker repo is shared across every agent and MCP server
in this project — set up once with
[`agents/internal_auditor/gcp_setup/create_artifact_registry.sh`](../../agents/internal_auditor/gcp_setup/create_artifact_registry.sh).
See [`gcp_setup/DEPLOY.md` §5](../../agents/internal_auditor/gcp_setup/DEPLOY.md) for the Console alternative.

```bash
export PROJECT_ID="$HOST_PROJECT"      # the script's required var
agents/internal_auditor/gcp_setup/create_artifact_registry.sh
```

Skip this if you've already run it for another image in the same
project — the repo is project-wide.

## 3. Build + push the image

From the repo root (one level above `mcp_servers/`):

```bash
gcloud builds submit mcp_servers/gcp_log_analyzer \
  --project="$HOST_PROJECT" \
  --tag "$IMAGE"
```

Cloud Build picks up the `Dockerfile` in `mcp_servers/gcp_log_analyzer/`,
builds the image, and pushes to AR. The image's `ENTRYPOINT` runs the
server with `MCP_TRANSPORT=streamable-http` listening on `:8080`.

## 4. Create the GSA and grant read access to logs

```bash
gcloud iam service-accounts create "$GSA_NAME" \
  --project="$HOST_PROJECT" \
  --display-name="GCP Log Analyzer MCP Server (sandboxed)"
```

If `LOGS_PROJECT == HOST_PROJECT`:

```bash
gcloud projects add-iam-policy-binding "$HOST_PROJECT" \
  --member="serviceAccount:${GSA_EMAIL}" \
  --role="roles/logging.viewer"
```

Cross-project (logs live elsewhere):

```bash
gcloud projects add-iam-policy-binding "$LOGS_PROJECT" \
  --member="serviceAccount:${GSA_EMAIL}" \
  --role="roles/logging.viewer"
```

For data-access logs, use `roles/logging.privateLogViewer` instead.

## 5. Workload Identity binding (GSA ↔ KSA)

Lets the in-cluster KSA impersonate the GSA without a static key.

```bash
gcloud iam service-accounts add-iam-policy-binding "$GSA_EMAIL" \
  --project="$HOST_PROJECT" \
  --role="roles/iam.workloadIdentityUser" \
  --member="serviceAccount:${HOST_PROJECT}.svc.id.goog[${NAMESPACE}/${KSA_NAME}]"
```

Create the KSA in the cluster and annotate it with the GSA:

```bash
kubectl create serviceaccount "$KSA_NAME" -n "$NAMESPACE"
kubectl annotate serviceaccount "$KSA_NAME" -n "$NAMESPACE" \
  "iam.gke.io/gcp-service-account=${GSA_EMAIL}"
```

The sandbox template's `podTemplate.spec.serviceAccountName` must
match `$KSA_NAME` so warm-pool pods pick it up.

## 6. Wire the image + KSA into the SandboxTemplate

Edit
[`agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml`](../../agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml)
and replace the placeholder image:

```bash
sed -i.bak "s|REPLACE_WITH_AR/mcp_servers/gcp-log-analyzer:0.1.0|$IMAGE|" \
  agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
```

The template also references `serviceAccountName: gcp-log-analyzer-mcp`
and expects `automountServiceAccountToken: true` (Workload Identity
needs the projected token).

## 7. Apply + verify

```bash
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml

kubectl -n "$NAMESPACE" get sandboxwarmpool gcp-log-analyzer-warmpool
# READY 2/2 within ~30s.

kubectl -n "$NAMESPACE" get pods -l mcp-server=gcp-log-analyzer
# 2 idle pods, status Running, ready 1/1.
```

Smoke-test a single claim from a debug pod inside the cluster:

```bash
kubectl -n "$NAMESPACE" apply -f - <<'EOF'
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata: { name: smoke-test, namespace: default }
spec:
  warmPoolRef: { name: gcp-log-analyzer-warmpool }
  lifecycle:  { shutdownPolicy: Delete }
EOF

POD_IP=$(kubectl -n "$NAMESPACE" get sandboxclaim smoke-test \
  -o jsonpath='{.status.sandbox.podIPs[0]}')

kubectl -n "$NAMESPACE" run mcp-curl --rm -it --restart=Never --image=curlimages/curl -- \
  curl -sS -X POST "http://${POD_IP}:8080/mcp" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'

kubectl -n "$NAMESPACE" delete sandboxclaim smoke-test
```

A JSON-RPC response with server info means the image, GSA binding,
and warm-pool plumbing are all healthy.

## Updating

```bash
export IMAGE_TAG=0.1.1
export IMAGE="${REGION}-docker.pkg.dev/${HOST_PROJECT}/${AR_REPO}/gcp-log-analyzer:${IMAGE_TAG}"
gcloud builds submit mcp_servers/gcp_log_analyzer \
  --project="$HOST_PROJECT" \
  --tag "$IMAGE"
```

Bump the `image:` in the `SandboxTemplate` and re-apply. The Agent
Sandbox controller drains the warm pool and refills with pods running
the new image.

```bash
sed -i.bak "s|gcp-log-analyzer:.*|gcp-log-analyzer:${IMAGE_TAG}|" \
  agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
```

## Cost notes

- Per-call **claim** has no inherent cost — the cost is the always-on
  warm pods (`replicas: N` × node CPU/memory share). Two `100m / 256Mi`
  request pods is a few cents/day on a small node pool.
- Cloud Logging API reads are charged separately, trivial for normal
  query volumes.
- Unlike the previous Cloud Run model there is no scale-to-zero — warm
  pods are kept running so that claims complete in sub-second.

## Tearing down

```bash
kubectl -n "$NAMESPACE" delete -f agents/internal_auditor/deployment/k8s/sandbox-log-analyzer.yaml
kubectl -n "$NAMESPACE" delete serviceaccount "$KSA_NAME"
gcloud iam service-accounts delete "$GSA_EMAIL" --project="$HOST_PROJECT"
gcloud artifacts docker images delete "$IMAGE" --project="$HOST_PROJECT" --delete-tags --quiet
```
