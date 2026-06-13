# Internal Auditor — storage setup

How to create the BigQuery dataset/tables and the Firestore database
manually in GCP. Two paths are offered for each store: a click-through
Console flow, and a Cloud Shell script. Pick whichever fits your context.

> **Substitute as you go.** Throughout this doc:
> - `PROJECT_ID` = the GCP project that will host both BigQuery and Firestore.
> - `BQ_LOCATION` = BigQuery dataset region, e.g. `US`, `EU`, `us-central1`.
> - `FIRESTORE_REGION` = Firestore location, e.g. `nam5` (US multi-region),
>   `eur3` (EU multi-region), or a single region like `us-central1`.

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

### Granting the roles

```bash
# Example — replace USER with user:you@example.com or
# serviceAccount:setup-sa@PROJECT_ID.iam.gserviceaccount.com
for ROLE in \
    roles/bigquery.dataOwner \
    roles/bigquery.jobUser \
    roles/datastore.owner \
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

## 4. Verify

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
```

---

## Option C — Terraform (covers all of §1–§3a)

If you'd rather declare the whole thing as code, see
[`../deployment/terraform/`](../deployment/terraform/). One
`terraform apply` provisions the BigQuery dataset + tables, the
Firestore database, both composite indexes, and the TTL policy.

```bash
cd ../deployment/terraform/
terraform init
terraform apply -var "project_id=my-project"
```

Seeding the implicit Firestore collections (§3b) is still a manual step
either way — Terraform has no resource for "empty Firestore collection".

---

## File inventory

| File                                       | What it is                                            |
| ------------------------------------------ | ----------------------------------------------------- |
| [`create_bigquery.sql`](./create_bigquery.sql) | Pure DDL — paste into the BQ Console SQL editor.  |
| [`create_bigquery.sh`](./create_bigquery.sh)   | `bq` CLI wrapper that runs the DDL in Cloud Shell. |
| [`create_firestore.sh`](./create_firestore.sh) | gcloud script: DB + composite indexes + TTL.      |
| `DEPLOY.md`                                | This document.                                        |
