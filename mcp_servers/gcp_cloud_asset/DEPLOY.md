# Deploying gcp-cloud-asset to Cloud Run

This deploys the MCP server as a Cloud Run service, reachable over HTTPS,
running as a dedicated service account with `roles/cloudasset.viewer` on the
scope it will analyze.

## Pick your variables

```bash
# Project that HOSTS the Cloud Run service (you pay for compute here).
export HOST_PROJECT=my-host-project

# Project (or folder/org) whose assets the server will analyze.
# Often the same as HOST_PROJECT; can be different.
export ASSET_PROJECT=my-asset-project

# Cloud Run region.
export REGION=us-central1

# Dedicated service account for the Cloud Run service.
export SA_NAME=gcp-cloud-asset-mcp
export SA_EMAIL="${SA_NAME}@${HOST_PROJECT}.iam.gserviceaccount.com"

# Service name (also becomes part of the URL).
export SERVICE=gcp-cloud-asset-mcp
```

## 1. Enable required APIs (one-time, in HOST_PROJECT)

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudasset.googleapis.com \
  --project="$HOST_PROJECT"
```

## 2. Create the service account

```bash
gcloud iam service-accounts create "$SA_NAME" \
  --project="$HOST_PROJECT" \
  --display-name="GCP Cloud Asset MCP Server"
```

## 3. Grant the service account read access to assets

If `ASSET_PROJECT == HOST_PROJECT`:

```bash
gcloud projects add-iam-policy-binding "$HOST_PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudasset.viewer"
```

If assets live in a different project (cross-project):

```bash
gcloud projects add-iam-policy-binding "$ASSET_PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudasset.viewer"
```

To analyze assets at a folder or org level, bind the role on the folder/org
instead:

```bash
gcloud resource-manager folders add-iam-policy-binding FOLDER_ID \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudasset.viewer"
```

## 3b. Grant Cloud Build IAM (one-time, easy to miss)

`gcloud run deploy --source` builds the container with Cloud Build, which
runs as the project's **Compute Engine default service account** in
projects created after mid-2024. That SA doesn't have build permissions
by default — without this grant the first deploy fails with:

> `<num>-compute@developer.gserviceaccount.com does not have storage.objects.get access to the google cloud storage object`

Fix it once:

```bash
PROJECT_NUMBER=$(gcloud projects describe "$HOST_PROJECT" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$HOST_PROJECT" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/cloudbuild.builds.builder"
```

## 4. Deploy to Cloud Run from source

Run this from the repo root (one level above `mcp_servers/`):

```bash
gcloud run deploy "$SERVICE" \
  --project="$HOST_PROJECT" \
  --region="$REGION" \
  --source=mcp_servers/gcp_cloud_asset \
  --service-account="$SA_EMAIL" \
  --no-allow-unauthenticated \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${ASSET_PROJECT},MCP_TRANSPORT=streamable-http" \
  --cpu=1 --memory=512Mi \
  --min-instances=0 --max-instances=3
```

What this does:

- `--source mcp_servers/gcp_cloud_asset` — Cloud Build picks up the
  `Dockerfile` in that directory, builds an image, pushes to Artifact
  Registry, and deploys.
- `--no-allow-unauthenticated` — only callers with `roles/run.invoker`
  on this service can hit it.
- `MCP_TRANSPORT=streamable-http` — flips the server out of stdio mode
  into HTTP mode; it listens on `$PORT` (set by Cloud Run to `8080`).
- `GOOGLE_CLOUD_PROJECT` — default project scope when callers don't pass
  `project_id` or `scope`.

Take note of the service URL printed at the end:
`https://gcp-cloud-asset-mcp-xxxxx-uc.a.run.app`

## 5. Grant invokers

Decide who can call the service. For a single user:

```bash
gcloud run services add-iam-policy-binding "$SERVICE" \
  --project="$HOST_PROJECT" \
  --region="$REGION" \
  --member="user:you@example.com" \
  --role="roles/run.invoker"
```

For a team via a Google Group:

```bash
gcloud run services add-iam-policy-binding "$SERVICE" \
  --project="$HOST_PROJECT" \
  --region="$REGION" \
  --member="group:my-team@example.com" \
  --role="roles/run.invoker"
```

## 6. Smoke-test the deployed server

```bash
TOKEN=$(gcloud auth print-identity-token)
SERVICE_URL=$(gcloud run services describe "$SERVICE" \
  --project="$HOST_PROJECT" --region="$REGION" \
  --format='value(status.url)')
```

Liveness check (server is up + auth works):

```bash
curl -sS -i \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  "$SERVICE_URL/mcp"
```

Real protocol handshake (proves MCP is actually working end-to-end):

```bash
curl -sS -i \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -X POST "$SERVICE_URL/mcp" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "protocolVersion": "2024-11-05",
      "capabilities": {},
      "clientInfo": {"name": "curl", "version": "0"}
    }
  }'
```

Expect a JSON-RPC response with server info and capabilities. A 401/403
means the `roles/run.invoker` binding from step 5 didn't take; a 404
means try `/sse` instead of `/mcp`.

## 7. Connect your MCP client

The connection URL is `${SERVICE_URL}/mcp` (streamable-http) or
`${SERVICE_URL}/sse` (SSE), depending on what the client supports.

Auth requires a Google identity token in `Authorization: Bearer <id-token>`.
Two options:

1. **Use `gcloud run services proxy` locally** for clients that only do
   stdio or untrusted HTTP:
   ```bash
   gcloud run services proxy "$SERVICE" \
     --project="$HOST_PROJECT" --region="$REGION" \
     --port=8080
   ```
   This opens an authenticated tunnel on `http://localhost:8080`. Point
   your MCP client at `http://localhost:8080/mcp`.

2. **If your client supports custom headers**, set an `Authorization`
   header with the output of `gcloud auth print-identity-token`. Note
   that token expires every ~1 hour.

## Updating the deployment

```bash
gcloud run deploy "$SERVICE" \
  --project="$HOST_PROJECT" \
  --region="$REGION" \
  --source=mcp_servers/gcp_cloud_asset
```

## Cost notes

- Cloud Run with `--min-instances=0` scales to zero when idle. You pay
  only for request time.
- Cloud Asset API calls are priced per 2,000 operations. Normal MCP usage
  is well under $1/month.

## Tearing down

```bash
gcloud run services delete "$SERVICE" \
  --project="$HOST_PROJECT" --region="$REGION"

gcloud iam service-accounts delete "$SA_EMAIL" \
  --project="$HOST_PROJECT"
```
