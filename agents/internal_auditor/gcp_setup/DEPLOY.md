# Internal Auditor — GCP setup

How to create the GCP resources the Internal Auditor needs:

- **Pub/Sub** topic + subscription that the orchestrator subscribes to
  for audit triggers (§4).
- **Artifact Registry** Docker repo that holds every agent + MCP server
  container image (§5).
- **BigQuery** dataset + tables that hold audit runs / findings / alerts
  (§1–§2). Used by the future Policy Agent.
- **Firestore** database + indexes + TTL for ground-truth precedents
  (§3). Used by the future Policy Agent.

Two paths are offered for each: a click-through Console flow, and a
Cloud Shell script. Pick whichever fits your context.

> **Substitute as you go.** Throughout this doc:
> - `PROJECT_ID` = the GCP project that will host all of the above.
> - `REGION` = Artifact Registry + GKE region, e.g. `us-central1`.
> - `BQ_LOCATION` = BigQuery dataset region, e.g. `US`, `EU`, `us-central1`.
> - `FIRESTORE_REGION` = Firestore location, e.g. `nam5` (US multi-region),
>   `eur3` (EU multi-region), or a single region like `us-central1`.
> - `GSA_EMAIL` = the orchestrator's Google Service Account email, e.g.
>   `internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com` (created
>   in [`../deployment/k8s/README.md`](../deployment/k8s/README.md) step 3).

---

## 0. Permissions you need on `PROJECT_ID`

Grant these to the human (or service account) that will run the scripts.
The "minimum" column lists the smallest set of predefined roles that
covers everything in this doc; the "easy mode" column is a single broad
role if you don't care about least-privilege for one-off setup.

### BigQuery (§1–§2)

| Action                                | Permission                                  | Minimum role                                    |
| ------------------------------------- | ------------------------------------------- | ----------------------------------------------- |
| Create the `internal_auditor` dataset | `bigquery.datasets.create`                  | `roles/bigquery.dataOwner` (project-level)      |
| Create the 3 tables                   | `bigquery.tables.create` + `.update`        | `roles/bigquery.dataEditor` on the dataset      |
| Run the CREATE TABLE DDL queries      | `bigquery.jobs.create`                      | `roles/bigquery.jobUser` (project-level)        |

- **Minimum**: `roles/bigquery.dataOwner` + `roles/bigquery.jobUser` at
  the project level.
- **Easy mode**: `roles/bigquery.admin` at the project level.

### Firestore (§3a)

| Action                                              | Permission                            | Minimum role                                   |
| --------------------------------------------------- | ------------------------------------- | ---------------------------------------------- |
| Enable the Firestore API                            | `serviceusage.services.enable`        | `roles/serviceusage.serviceUsageAdmin`         |
| Create database `internal-auditor-db`               | `datastore.databases.create`          | `roles/datastore.owner` (project-level)        |
| Create the 2 composite indexes                      | `datastore.indexes.create`            | `roles/datastore.indexAdmin`                   |
| Enable TTL on `ground_truth_decisions.expires_at`   | `datastore.databases.update`          | `roles/datastore.owner`                        |

- **Minimum**: `roles/datastore.owner` + `roles/serviceusage.serviceUsageAdmin`.
- **Easy mode**: `roles/owner` on the project covers all of the above
  (and everything else — use only in sandboxes).

### Seeding placeholder docs (§3b)

| Action                                       | Permission              | Minimum role                |
| -------------------------------------------- | ----------------------- | --------------------------- |
| Write the `_seed` doc into each collection   | `datastore.entities.create` | `roles/datastore.user`  |

Already covered by `roles/datastore.owner` above.

### Pub/Sub (§4)

| Action                                          | Permission                            | Minimum role                          |
| ----------------------------------------------- | ------------------------------------- | ------------------------------------- |
| Enable the Pub/Sub API                          | `serviceusage.services.enable`        | `roles/serviceusage.serviceUsageAdmin` |
| Create topic + subscription                     | `pubsub.topics.create`, `pubsub.subscriptions.create` | `roles/pubsub.editor` (project-level) |
| Grant the orchestrator GSA `pubsub.subscriber`  | `pubsub.subscriptions.setIamPolicy`   | `roles/pubsub.admin` on the subscription (or project-level) |

- **Minimum**: `roles/pubsub.admin` + `roles/serviceusage.serviceUsageAdmin`.
- **Easy mode**: `roles/owner` on the project.

### Artifact Registry (§5)

| Action                                                       | Permission                                         | Minimum role                                  |
| ------------------------------------------------------------ | -------------------------------------------------- | --------------------------------------------- |
| Enable the AR + Cloud Build APIs                             | `serviceusage.services.enable`                     | `roles/serviceusage.serviceUsageAdmin`        |
| Create the Docker repo                                       | `artifactregistry.repositories.create`             | `roles/artifactregistry.admin` (project-level) |
| Grant the Compute SA `cloudbuild.builds.builder` (one-time)  | `resourcemanager.projects.setIamPolicy`            | `roles/resourcemanager.projectIamAdmin`       |

- **Minimum**: `roles/artifactregistry.admin` + `roles/resourcemanager.projectIamAdmin` + `roles/serviceusage.serviceUsageAdmin`.
- **Easy mode**: `roles/owner` on the project.

### Granting the roles

```bash
# Example — replace USER with user:you@example.com or
# serviceAccount:setup-sa@PROJECT_ID.iam.gserviceaccount.com
for ROLE in \
    roles/bigquery.dataOwner \
    roles/bigquery.jobUser \
    roles/datastore.owner \
    roles/pubsub.admin \
    roles/artifactregistry.admin \
    roles/resourcemanager.projectIamAdmin \
    roles/serviceusage.serviceUsageAdmin; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="$USER" --role="$ROLE"
done
```

Or in the Console: IAM & Admin → IAM → **Grant access** → paste the
principal, add each role, **Save**.

> **If you only have `roles/editor`** on the project: it covers BigQuery
> table/dataset creation and Firestore reads/writes, but **not**
> `datastore.databases.create` or `datastore.indexes.create`. You'll need
> at least `roles/datastore.owner` added on top for §3a.

---

## 1. BigQuery: dataset `internal_auditor`

### Option A — Console UI

1. Open <https://console.cloud.google.com/bigquery>.
2. Confirm the project picker shows `PROJECT_ID`.
3. In the **Explorer** panel, click the project's three-dot menu →
   **Create dataset**.
4. Fill in:
   - **Dataset ID**: `internal_auditor`
   - **Location type**: Multi-region (or single region — match your other
     analytics data).
   - **Location**: `BQ_LOCATION`.
   - **Default table expiration**: leave blank. Compliance data is
     immutable; never auto-expire.
5. Click **Create dataset**.

### Option B — Cloud Shell

```bash
bq --location="$BQ_LOCATION" mk -d \
  --description "Internal Auditor compliance ledger" \
  "$PROJECT_ID:internal_auditor"
```

---

## 2. BigQuery: tables (`audit_runs`, `audit_findings`, `audit_alerts`)

### Option A — Console SQL editor (paste DDL)

1. In the BigQuery Console, click **Compose new query**.
2. Open [`create_bigquery.sql`](./create_bigquery.sql) and copy the first
   `CREATE TABLE IF NOT EXISTS \`internal_auditor.audit_runs\` (...);`
   block.
3. Paste it in, click **Run**, wait for the green check.
4. Repeat for `audit_findings`, then `audit_alerts`. (The SQL editor
   only runs one statement per tab.)
5. Verify in the Explorer: the three tables appear under
   `internal_auditor`, each with its description and partition column
   shown in the **Details** tab.

### Option B — Cloud Shell (`bq` CLI, one shot)

```bash
export PROJECT_ID=my-project
export BQ_LOCATION=US
cd terraform
./create_bigquery.sh
```

The script creates the dataset (if missing) then runs the DDL in
`create_bigquery.sql`. Re-running is safe — `CREATE TABLE IF NOT EXISTS`
skips existing tables.

### What you should see

| Table              | Partition           | Cluster                     |
| ------------------ | ------------------- | --------------------------- |
| `audit_runs`       | `DATE(started_at)`  | `trigger_type, verdict`     |
| `audit_findings`   | `DATE(found_at)`    | `run_id, detected_by, verdict` |
| `audit_alerts`     | `DATE(dispatched_at)` | `severity, pubsub_topic`  |

---

## 3. Firestore: database `internal-auditor-db`

Firestore has two pieces that need explicit creation (the named database
and any composite indexes) and one piece that is **implicit** (collections
materialize on first write — there's no "create collection" call).

### 3a. Database + indexes + TTL

#### Option A — Console UI

1. Open <https://console.cloud.google.com/firestore>.
2. Confirm the project picker shows `PROJECT_ID`.
3. If this is your first Firestore database in the project, click
   **Create database**. Otherwise click the database picker → **Create
   database**.
4. Fill in:
   - **Database ID**: `internal-auditor-db`
   - **Database mode**: **Native mode** (required — Datastore mode lacks
     subcollections and the TTL feature we use).
   - **Location**: `FIRESTORE_REGION` (multi-region recommended for HA).
   - **Security rules**: **Locked mode**. The auditor accesses Firestore
     via a service account; deny-by-default keeps end-users out.
5. Click **Create database**.

Then add the two composite indexes the access patterns in `schemas.py`
require:

6. In the database, go to **Indexes** → **Composite** → **Create index**.
7. Index 1 — fast lookup of active precedent by pattern:
   - **Collection ID**: `ground_truth_decisions`
   - **Query scope**: Collection
   - **Fields** (in order, all ascending):
     `pattern_key`, `verdict`, `is_active`
8. Click **Create**. Repeat:
9. Index 2 — TTL sweep:
   - **Collection ID**: `ground_truth_decisions`
   - **Query scope**: Collection
   - **Fields**: `is_active` asc, `expires_at` asc
10. Then enable TTL for soft-expiry: **TTL** tab → **Create policy** →
    Collection `ground_truth_decisions`, field `expires_at`.

Index builds take a few minutes on an empty database, longer once data exists.

#### Option B — Cloud Shell

```bash
export PROJECT_ID=my-project
export FIRESTORE_REGION=nam5
cd terraform
./create_firestore.sh
```

Creates the database, both composite indexes, and the TTL policy in one go.

### 3b. Seed the collections (`ground_truth_decisions`, `schema_registry`)

Collections don't exist until something is written to them. To make them
visible in the Console explorer and let the auditor agent start querying
without "collection not found" errors, drop one placeholder doc into each:

1. In Firestore Console → database `internal-auditor-db` → **Data** tab.
2. Click **Start collection**.
3. **Collection ID**: `ground_truth_decisions`.
4. **Document ID**: `_seed` (or **Auto-ID**).
5. Add a single field `is_seed` (boolean, `true`).
6. **Save**.
7. Repeat for collection `schema_registry`, same `_seed` doc.

You can delete the `_seed` docs later — the collection stays as long as
the auditor has written real docs in the meantime.

---

## 4. Pub/Sub: trigger topic + subscription

The orchestrator pod runs a Pub/Sub subscriber as its main process; it
opens a streaming pull on the subscription as its first action. **If
the subscription doesn't exist when the pod boots, it crash-loops on
`NotFound`.** Do this before applying
[`../deployment/k8s/deployment.yaml`](../deployment/k8s/deployment.yaml).

Default names (override via env if you must — see the script header):

| Resource           | Name                                 |
| ------------------ | ------------------------------------ |
| Trigger topic      | `internal-auditor-triggers`          |
| Pull subscription  | `internal-auditor-triggers-sub`      |
| DLQ topic (opt)    | `internal-auditor-triggers-dlq`      |

### Option A — Console UI

1. Open <https://console.cloud.google.com/cloudpubsub/topic/list>.
2. **Create topic** → ID `internal-auditor-triggers`, leave defaults,
   **Create**.
3. Open the topic → **Subscriptions** tab → **Create subscription**:
   - **ID**: `internal-auditor-triggers-sub`
   - **Delivery type**: Pull
   - **Acknowledgement deadline**: 600 seconds (10 minutes) — give an
     audit room to finish before Pub/Sub redelivers.
   - **Message retention duration**: 1 day.
   - **Expiration period**: Never.
   - (Optional) **Dead-lettering**: enable, point at a topic you create
     first named `internal-auditor-triggers-dlq`, max delivery
     attempts 5.
4. On the new subscription, **Permissions** tab → **Add principal** →
   paste the orchestrator GSA (`GSA_EMAIL`) → role
   `Pub/Sub Subscriber` → **Save**.

### Option B — Cloud Shell

```bash
export GSA_EMAIL="internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com"
./create_pubsub.sh

# With DLQ:
CREATE_DLQ=1 ./create_pubsub.sh
```

The script is idempotent — re-runs are safe; existing resources are
skipped, IAM bindings are noop on repeat.

---

## 5. Artifact Registry: Docker repo `agents`

Every agent + MCP server container image lives here. Image references
across this repo all look like:

```
${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/<image-name>:<tag>
```

where `AR_REPO` defaults to `agents`. You only need one Docker repo for
the whole project — the orchestrator image, `gcp-log-analyzer`,
`gcp-cloud-asset`, and any future agents all share it.

### Option A — Console UI

1. Open <https://console.cloud.google.com/artifacts>.
2. Confirm the project picker shows `PROJECT_ID`.
3. **+ Create repository**:
   - **Name**: `agents`
   - **Format**: Docker
   - **Mode**: Standard
   - **Location type**: Region → pick `REGION` (e.g. `us-central1`).
   - **Encryption**: Google-managed (default).
   - **Immutable image tags**: off (let `:latest` move).
4. **Create**.
5. (One-time, for `gcloud builds submit` to work) IAM & Admin → IAM →
   find `<project-number>-compute@developer.gserviceaccount.com` →
   **Edit principal** → **Add role** → `Cloud Build Service Account`
   (`roles/cloudbuild.builds.builder`) → **Save**.

### Option B — Cloud Shell

```bash
export REGION=us-central1     # match your cluster region
./create_artifact_registry.sh
```

The script enables `artifactregistry.googleapis.com` and
`cloudbuild.googleapis.com`, creates the `agents` repo in `$REGION`,
and grants the Cloud Build SA the IAM role it needs to push to it.
Idempotent.

> **Why the Cloud Build IAM step?** In projects created after mid-2024,
> Cloud Build runs as the Compute Engine default SA, which by default
> can't push to AR (or read its own staging bucket, or write build
> logs). One role — `roles/cloudbuild.builds.builder` — covers all of
> it. Without this, your first `gcloud builds submit` fails with:
> `<num>-compute@developer.gserviceaccount.com does not have storage.objects.get access`

---

## 6. Verify

```bash
# BigQuery: tables exist
bq ls --project_id=$PROJECT_ID internal_auditor
# expect: audit_runs, audit_findings, audit_alerts

# BigQuery: partition + cluster is set
bq show --project_id=$PROJECT_ID internal_auditor.audit_runs

# Firestore: database exists
gcloud firestore databases describe \
  --project=$PROJECT_ID --database=internal-auditor-db

# Firestore: indexes built (state should be READY)
gcloud firestore indexes composite list \
  --project=$PROJECT_ID --database=internal-auditor-db

# Pub/Sub: topic + subscription exist
gcloud pubsub topics describe internal-auditor-triggers --project=$PROJECT_ID
gcloud pubsub subscriptions describe internal-auditor-triggers-sub --project=$PROJECT_ID

# Pub/Sub: orchestrator GSA can subscribe
gcloud pubsub subscriptions get-iam-policy internal-auditor-triggers-sub \
  --project=$PROJECT_ID
# expect: a binding listing GSA_EMAIL under roles/pubsub.subscriber

# Artifact Registry: repo exists
gcloud artifacts repositories describe agents \
  --project=$PROJECT_ID --location=$REGION

# Artifact Registry: Cloud Build SA has builder role
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten='bindings[].members[]' \
  --filter='bindings.role=roles/cloudbuild.builds.builder' \
  --format='value(bindings.members)'
# expect: a service account ending in @developer.gserviceaccount.com
```

---

## Option C — Terraform (covers §1–§3a only)

If you'd rather declare BQ + Firestore as code, see
[`../deployment/terraform/`](../deployment/terraform/). One
`terraform apply` provisions the BigQuery dataset + tables, the
Firestore database, both composite indexes, and the TTL policy.

```bash
cd ../deployment/terraform/
terraform init
terraform apply -var "project_id=my-project"
```

Pub/Sub (§4), Artifact Registry (§5), and the §3b Firestore collection
seed are still manual either way — Terraform's `internal_auditor`
module doesn't cover them today.

---

## File inventory

| File                                                           | What it is                                            |
| -------------------------------------------------------------- | ----------------------------------------------------- |
| [`create_bigquery.sql`](./create_bigquery.sql)                 | Pure DDL — paste into the BQ Console SQL editor.      |
| [`create_bigquery.sh`](./create_bigquery.sh)                   | `bq` CLI wrapper that runs the DDL in Cloud Shell.    |
| [`create_firestore.sh`](./create_firestore.sh)                 | gcloud script: DB + composite indexes + TTL.          |
| [`create_pubsub.sh`](./create_pubsub.sh)                       | gcloud script: API enable, topic, subscription, GSA IAM binding (+ optional DLQ). |
| [`create_artifact_registry.sh`](./create_artifact_registry.sh) | gcloud script: APIs enable, Docker repo, Cloud Build SA binding. |
| `DEPLOY.md`                                                    | This document.                                        |
