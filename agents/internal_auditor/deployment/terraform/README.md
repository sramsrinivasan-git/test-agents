# Internal Auditor — Terraform

Creates the same resources as the manual setup under `../../gcp_setup/`:

- BigQuery dataset `internal_auditor` + tables `audit_runs`,
  `audit_findings`, `audit_alerts` (partitioned + clustered).
- Firestore Native-mode database `internal-auditor-db` with two
  composite indexes on `ground_truth_decisions` and a TTL policy on
  `expires_at`.

Pick this path over `../../gcp_setup/` when you want reproducible,
version-controlled infra. Keep the manual scripts for ad-hoc / one-shot
setup where pulling in Terraform tooling is overkill.

## Usage

```bash
cd terraform/
terraform init
terraform plan -var "project_id=my-project"
terraform apply -var "project_id=my-project"
```

For non-default locations:

```bash
terraform apply \
  -var "project_id=my-project" \
  -var "bq_location=EU" \
  -var "firestore_region=eur3"
```

## Layout

| File             | Purpose                                                |
| ---------------- | ------------------------------------------------------ |
| `versions.tf`    | Terraform + google provider version pins.              |
| `variables.tf`   | Inputs: `project_id`, `bq_location`, `firestore_region`. |
| `main.tf`        | Provider config + API enablement.                      |
| `bigquery.tf`    | Dataset + 3 tables.                                    |
| `firestore.tf`   | Database + 2 composite indexes + TTL field.            |
| `outputs.tf`     | Useful IDs to consume downstream.                      |
| `schemas/*.json` | BigQuery table schemas (BQ CLI JSON format).           |

## Notes

- **State** is local. For team use, configure a GCS backend in
  `versions.tf` before the first `terraform apply`.
- **Collections** in Firestore (`ground_truth_decisions`,
  `schema_registry`) materialize on first write — Terraform doesn't
  create them. To make them visible in the Console explorer, drop a
  placeholder doc in each (see `../../gcp_setup/DEPLOY.md` §3b).
- **Deletion protection** is on for all BQ tables. To `terraform destroy`,
  set `deletion_protection = false`, `terraform apply`, then destroy.
- **Schema source of truth**: `schemas/*.json`. Same JSON format the
  `bq mk --schema` CLI consumes, so it's reusable outside Terraform.
