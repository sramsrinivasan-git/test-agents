#!/usr/bin/env bash
# Create the Internal Auditor BigQuery dataset + 3 tables via the `bq` CLI.
#
# Use this in Cloud Shell as an alternative to pasting create_bigquery.sql
# into the Console SQL editor. Result is identical: same dataset, tables,
# partitioning, clustering, and column descriptions.
#
# Usage:
#   export PROJECT_ID=my-project
#   export BQ_LOCATION=US                # or EU / us-central1 / etc.
#   ./create_bigquery.sh
#
# Re-running is safe: --force on dataset creation is intentionally omitted,
# and CREATE TABLE IF NOT EXISTS skips existing tables.

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required (export PROJECT_ID=my-project)}"
: "${BQ_LOCATION:=US}"

DATASET="internal_auditor"
SQL_FILE="$(dirname "$0")/create_bigquery.sql"

echo "==> Project:  $PROJECT_ID"
echo "==> Dataset:  $DATASET"
echo "==> Location: $BQ_LOCATION"

# 1. Dataset (idempotent: ignore the "already exists" error).
echo "==> Creating dataset $DATASET (skipped if it already exists)..."
bq --location="$BQ_LOCATION" --project_id="$PROJECT_ID" mk -d \
  --description "Internal Auditor compliance ledger" \
  "$DATASET" 2>/dev/null || echo "    (dataset already exists, continuing)"

# 2. Tables — drive `bq query` with the DDL file so the SQL stays the
#    single source of truth.
echo "==> Creating tables from $SQL_FILE..."
bq --project_id="$PROJECT_ID" query --use_legacy_sql=false < "$SQL_FILE"

echo "==> Done. Verify with:"
echo "    bq ls --project_id=$PROJECT_ID $DATASET"
