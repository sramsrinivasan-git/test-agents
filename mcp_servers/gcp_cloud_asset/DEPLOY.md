# Deploying gcp-cloud-asset to GKE (as a sandboxed warm-pool MCP server)

This server runs as **pre-warmed gVisor-sandboxed pods inside a GKE
cluster**, managed by the GKE Agent Sandbox controller's
`SandboxWarmPool`. The Internal Auditor orchestrator claims one idle
pod per specialist tool call, talks to it over MCP, and releases it.

The deployment artifact is therefore an **Artifact Registry image**,
not a Cloud Run service. The actual `SandboxTemplate` + `SandboxWarmPool`
manifests live alongside the orchestrator in
[`agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml`](../../agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml).
This doc covers what's specific to **this MCP server**: building the
image, the GSA + Workload Identity binding, and the (possibly
multi-project / folder / org) IAM grants the sandboxed pods need to
read Cloud Asset Inventory.

At runtime the orchestrator passes `project_id` or `scope` on each tool
call, so a single deployment can target any project/folder/org the GSA
has access to. The `GOOGLE_CLOUD_PROJECT` env var set on the
`SandboxTemplate` is only the **default** when no `project_id` is
supplied.

## Pick your variables

```bash
# GCP project hosting the GKE cluster + Artifact Registry.
export HOST_PROJECT=my-host-project

# Default project whose assets the server analyzes when no project_id
# is supplied by the caller. Often the same as HOST_PROJECT.
export ASSET_PROJECT=my-asset-project

# AR repo + region.
export REGION=us-central1
export AR_REPO=agents
export IMAGE_TAG=0.1.0
export IMAGE="${REGION}-docker.pkg.dev/${HOST_PROJECT}/${AR_REPO}/gcp-cloud-asset:${IMAGE_TAG}"

# Identities. The GSA holds GCP IAM; the KSA is mounted into the
# sandbox pods and is bound to the GSA via Workload Identity.
export GSA_NAME=gcp-cloud-asset-mcp
export GSA_EMAIL="${GSA_NAME}@${HOST_PROJECT}.iam.gserviceaccount.com"
export KSA_NAME=gcp-cloud-asset-mcp
export NAMESPACE=default              # where the warm pool lives
```

## 1. Enable required APIs (one-time, in HOST_PROJECT)

```bash
gcloud services enable \
  container.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  iamcredentials.googleapis.com \
  cloudasset.googleapis.com \
  logging.googleapis.com \
  --project="$HOST_PROJECT"
```

Cloud Asset API also needs to be enabled in every **target** project,
folder, or org you want to read from — not just `HOST_PROJECT`.

## 2. Create the Artifact Registry repo (one-time)

```bash
gcloud artifacts repositories create "$AR_REPO" \
  --project="$HOST_PROJECT" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Container images for the internal-auditor agent stack"
```

## 3. Build + push the image

```bash
gcloud builds submit mcp_servers/gcp_cloud_asset \
  --project="$HOST_PROJECT" \
  --tag "$IMAGE"
```

> **One-time Cloud Build IAM gotcha:** in projects created after
> mid-2024, Cloud Build runs as the Compute Engine default SA, which
> needs `roles/cloudbuild.builds.builder`:
> ```bash
> PROJECT_NUMBER=$(gcloud projects describe "$HOST_PROJECT" --format='value(projectNumber)')
> gcloud projects add-iam-policy-binding "$HOST_PROJECT" \
>   --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
>   --role="roles/cloudbuild.builds.builder"
> ```

## 4. Create the GSA

```bash
gcloud iam service-accounts create "$GSA_NAME" \
  --project="$HOST_PROJECT" \
  --display-name="GCP Cloud Asset MCP Server (sandboxed)"
```

## 5. Grant read access on every scope you want to analyze

The image is built **once**; you repeat this step for every project /
folder / org the server should be able to inspect — no redeploy needed.

Two roles per scope:

| Role | Purpose |
|---|---|
| `roles/cloudasset.viewer` | Read Cloud Asset Inventory (resources, IAM policies, history) |
| `roles/logging.viewer` | Read Cloud Logging runtime logs (audit history) |

Use `roles/logging.privateLogViewer` if data-access audit logs are
also needed.

**Single project:**

```bash
for ROLE in roles/cloudasset.viewer roles/logging.viewer; do
  gcloud projects add-iam-policy-binding "$ASSET_PROJECT" \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="$ROLE"
done
```

**Multiple projects:**

```bash
for PROJECT in project-a project-b project-c; do
  for ROLE in roles/cloudasset.viewer roles/logging.viewer; do
    gcloud projects add-iam-policy-binding "$PROJECT" \
      --member="serviceAccount:${GSA_EMAIL}" \
      --role="$ROLE"
  done
done
```

**Entire folder or org** (covers all projects underneath — most
convenient for large environments):

```bash
for ROLE in roles/cloudasset.viewer roles/logging.viewer; do
  gcloud resource-manager folders add-iam-policy-binding FOLDER_ID \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="$ROLE"
done

# or at the org level:
for ROLE in roles/cloudasset.viewer roles/logging.viewer; do
  gcloud organizations add-iam-policy-binding ORG_ID \
    --member="serviceAccount:${GSA_EMAIL}" \
    --role="$ROLE"
done
```

## 6. Workload Identity binding (GSA ↔ KSA)

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

## 7. Wire the image + KSA into the SandboxTemplate

Edit
[`agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml`](../../agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml)
and replace the placeholder image:

```bash
sed -i.bak "s|REPLACE_WITH_AR/mcp_servers/gcp-cloud-asset:0.1.0|$IMAGE|" \
  agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml
```

The template also references `serviceAccountName: gcp-cloud-asset-mcp`
and expects `automountServiceAccountToken: true` (Workload Identity
needs the projected token).

## 8. Apply + verify

```bash
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml

kubectl -n "$NAMESPACE" get sandboxwarmpool gcp-cloud-asset-warmpool
# READY 2/2 within ~30s.

kubectl -n "$NAMESPACE" get pods -l mcp-server=gcp-cloud-asset
# 2 idle pods, status Running, ready 1/1.
```

Smoke-test a single claim from inside the cluster:

```bash
kubectl -n "$NAMESPACE" apply -f - <<'EOF'
apiVersion: extensions.agents.x-k8s.io/v1beta1
kind: SandboxClaim
metadata: { name: smoke-test, namespace: default }
spec:
  warmPoolRef: { name: gcp-cloud-asset-warmpool }
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

## Updating

```bash
export IMAGE_TAG=0.1.1
export IMAGE="${REGION}-docker.pkg.dev/${HOST_PROJECT}/${AR_REPO}/gcp-cloud-asset:${IMAGE_TAG}"
gcloud builds submit mcp_servers/gcp_cloud_asset \
  --project="$HOST_PROJECT" \
  --tag "$IMAGE"

sed -i.bak "s|gcp-cloud-asset:.*|gcp-cloud-asset:${IMAGE_TAG}|" \
  agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml
kubectl apply -f agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml
```

The Agent Sandbox controller drains the warm pool and refills with
pods running the new image.

## Cost notes

- Per-call **claim** has no inherent cost — the cost is the always-on
  warm pods (`replicas: N` × node CPU/memory share). Two `100m / 256Mi`
  request pods is a few cents/day on a small node pool.
- Cloud Asset and Logging API reads are charged separately, trivial
  for normal query volumes.
- Unlike the previous Cloud Run model there is no scale-to-zero — warm
  pods are kept running so that claims complete in sub-second.

## Tearing down

```bash
kubectl -n "$NAMESPACE" delete -f agents/internal_auditor/deployment/k8s/sandbox-cloud-asset.yaml
kubectl -n "$NAMESPACE" delete serviceaccount "$KSA_NAME"
gcloud iam service-accounts delete "$GSA_EMAIL" --project="$HOST_PROJECT"
gcloud artifacts docker images delete "$IMAGE" --project="$HOST_PROJECT" --delete-tags --quiet
```
