# Creating the GCP resources via the Cloud Console UI

This walkthrough mirrors `terraform/schema.py`. Each section corresponds
to one resource block in `schema.py` so you can cross-check that what you
clicked matches the declared desired state.

> **Substitute as you go.** Throughout this doc:
> - `HOST_PROJECT` = the project that will run the Cloud Run service.
> - `LOGS_PROJECT` = the project whose Cloud Logging data you want to read.
>   May equal `HOST_PROJECT`.
> - `REGION` = e.g. `us-central1`.
> - `SA_NAME` = `gcp-log-analyzer-mcp`.
> - `SERVICE` = `gcp-log-analyzer-mcp`.

---

## 1. Enable required APIs (`schema.py: EnabledApi`)

In **`HOST_PROJECT`** enable:

1. Open <https://console.cloud.google.com/apis/library>.
2. Confirm the project picker (top bar) shows `HOST_PROJECT`.
3. Search and enable each of:
   - **Cloud Run Admin API** (`run.googleapis.com`)
   - **Cloud Build API** (`cloudbuild.googleapis.com`)
   - **Artifact Registry API** (`artifactregistry.googleapis.com`)
   - **Cloud Logging API** (`logging.googleapis.com`)

In **`LOGS_PROJECT`** (skip if same as `HOST_PROJECT`):

4. Switch the project picker to `LOGS_PROJECT`.
5. Enable **Cloud Logging API** (`logging.googleapis.com`).

---

## 2. Create the service account (`schema.py: ServiceAccount`)

1. Go to <https://console.cloud.google.com/iam-admin/serviceaccounts>.
2. Project picker → `HOST_PROJECT`.
3. Click **Create service account**.
4. **Service account name**: `GCP Log Analyzer MCP Server`.
5. **Service account ID**: `gcp-log-analyzer-mcp` (auto-fills).
6. Click **Create and continue**, then **Done** (skip optional steps).

Record the full email: `gcp-log-analyzer-mcp@HOST_PROJECT.iam.gserviceaccount.com`.

---

## 3. Grant IAM bindings (`schema.py: IamBinding`)

### 3a. Logs reader on `LOGS_PROJECT`

1. Go to <https://console.cloud.google.com/iam-admin/iam>.
2. Project picker → `LOGS_PROJECT`.
3. Click **Grant access**.
4. **New principals**: paste the SA email from step 2.
5. **Role**: `Logs Viewer` (`roles/logging.viewer`).
   - Use `Private Logs Viewer` (`roles/logging.privateLogViewer`) instead if
     you need to read data-access logs.
6. **Save**.

### 3b. Cloud Build builder on the compute default SA

`gcloud run deploy --source` (and the Console's "Deploy from source") use
Cloud Build, which runs as the Compute Engine default SA in projects
created after mid-2024. Without this it fails on first deploy.

1. Find the compute default SA email: open
   <https://console.cloud.google.com/welcome> → look up `Project number`
   in the dashboard cards; the SA is
   `PROJECT_NUMBER-compute@developer.gserviceaccount.com`.
2. <https://console.cloud.google.com/iam-admin/iam> → project picker = `HOST_PROJECT`.
3. Find that principal in the list (or **Grant access** with it).
4. Add role: `Cloud Build Service Account` (`roles/cloudbuild.builds.builder`).
5. **Save**.

---

## 4. Deploy the Cloud Run service (`schema.py: CloudRunService`)

The Console can't `--source`-deploy from a local checkout directly — push
this repo to GitHub / Cloud Source Repositories first, OR run
`gcloud run deploy ... --source mcp_servers/gcp_log_analyzer` from your
laptop once (the result is identical to what the UI would produce).

If using the Console:

1. <https://console.cloud.google.com/run> → project picker = `HOST_PROJECT`.
2. **Create service** → **Continuously deploy from a repository** (or
   **Deploy one revision from an existing container image** if you've
   already built one in Artifact Registry).
3. Connect the GitHub repo containing this code.
4. **Build configuration**:
   - **Source location**: `/mcp_servers/gcp_log_analyzer`
   - **Build type**: Dockerfile
5. **Service settings**:
   - **Service name**: `gcp-log-analyzer-mcp`
   - **Region**: `REGION`
   - **CPU allocation**: Only during request processing
   - **Authentication**: **Require authentication** (do NOT allow unauthenticated)
6. **Container, networking, security** → **Container** tab:
   - **Memory**: `512 MiB`
   - **CPU**: `1`
   - **Environment variables**:
     - `MCP_TRANSPORT` = `streamable-http`
     - `GOOGLE_CLOUD_PROJECT` = `LOGS_PROJECT`
7. **Container, networking, security** → **Security** tab:
   - **Service account** = `gcp-log-analyzer-mcp@HOST_PROJECT.iam.gserviceaccount.com`
8. **Revision autoscaling**:
   - **Min instances**: `0`
   - **Max instances**: `3`
9. **Create**. Wait for the first revision to go green.

Note the service URL shown at the top of the service detail page:
`https://gcp-log-analyzer-mcp-xxxxx-uc.a.run.app`.

---

## 5. Grant invokers (`schema.py: CloudRunInvoker`)

1. <https://console.cloud.google.com/run> → click the `gcp-log-analyzer-mcp` service.
2. **Permissions** tab → **Add principal**.
3. **New principals**: a user email, a Google Group, or a service account.
4. **Role**: `Cloud Run Invoker` (`roles/run.invoker`).
5. **Save**.

Repeat for each caller that needs access.

---

## 6. Smoke-test

In Cloud Shell (top-right `>_` icon in the Console):

```bash
TOKEN=$(gcloud auth print-identity-token)
SERVICE_URL=$(gcloud run services describe gcp-log-analyzer-mcp \
  --project=HOST_PROJECT --region=REGION --format='value(status.url)')

curl -sS -i \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  "$SERVICE_URL/mcp"
```

A 200 or a JSON-RPC response means the service is healthy and IAM is wired up.
A 401/403 means the invoker grant from step 5 didn't apply to you.

---

## Cross-reference cheatsheet

| `schema.py` block        | Console location                                |
| ------------------------ | ----------------------------------------------- |
| `EnabledApi`             | APIs & Services → Library                       |
| `ServiceAccount`         | IAM & Admin → Service Accounts                  |
| `IamBinding`             | IAM & Admin → IAM                               |
| `CloudRunService`        | Cloud Run → Create service                      |
| `CloudRunInvoker`        | Cloud Run → service → Permissions tab           |
