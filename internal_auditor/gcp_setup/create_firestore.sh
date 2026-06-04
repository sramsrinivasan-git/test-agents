#!/usr/bin/env bash
# Create the Internal Auditor Firestore database + composite indexes.
#
# Firestore collections (`ground_truth_decisions`, `schema_registry`) are
# implicit — they spring into existence on first document write. This
# script:
#   1. Creates the named database `internal-auditor-db` in Native mode.
#   2. Creates the composite indexes the access patterns in schemas.py
#      require (pattern_key + verdict; pattern_key + decided_at for TTL).
#   3. Enables Firestore TTL on the `expires_at` field of
#      `ground_truth_decisions` so soft-expired precedents auto-delete.
#
# After running this, use the Console UI (or any SDK) to seed the first
# document in each collection so the collection becomes visible in the
# Console explorer (see DEPLOY.md §3b).
#
# Usage:
#   export PROJECT_ID=my-project
#   export FIRESTORE_REGION=nam5          # or eur3 / us-central1 / etc.
#   ./create_firestore.sh

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required (export PROJECT_ID=my-project)}"
: "${FIRESTORE_REGION:=nam5}"

DB="internal-auditor-db"

echo "==> Project:  $PROJECT_ID"
echo "==> Database: $DB ($FIRESTORE_REGION, Native mode)"

# 1. Enable the API (idempotent).
gcloud services enable firestore.googleapis.com --project="$PROJECT_ID"

# 2. Create the named database. `gcloud firestore databases create` errors
#    if the database already exists; swallow that one specific failure.
echo "==> Creating database $DB..."
gcloud firestore databases create \
  --project="$PROJECT_ID" \
  --database="$DB" \
  --location="$FIRESTORE_REGION" \
  --type=firestore-native 2>&1 | tee /tmp/fs-create.log || \
  grep -q "already exists" /tmp/fs-create.log

# 3. Composite indexes for ground_truth_decisions.
#    Access patterns:
#      a) look up active precedent by (pattern_key, verdict, is_active)
#      b) sweep expired precedents by (is_active, expires_at)
echo "==> Creating composite indexes on ground_truth_decisions..."

gcloud firestore indexes composite create \
  --project="$PROJECT_ID" \
  --database="$DB" \
  --collection-group=ground_truth_decisions \
  --query-scope=COLLECTION \
  --field-config=field-path=pattern_key,order=ascending \
  --field-config=field-path=verdict,order=ascending \
  --field-config=field-path=is_active,order=ascending

gcloud firestore indexes composite create \
  --project="$PROJECT_ID" \
  --database="$DB" \
  --collection-group=ground_truth_decisions \
  --query-scope=COLLECTION \
  --field-config=field-path=is_active,order=ascending \
  --field-config=field-path=expires_at,order=ascending

# 4. TTL policy on ground_truth_decisions.expires_at.
#    Docs are auto-deleted within ~24h of expires_at passing.
echo "==> Enabling TTL on ground_truth_decisions.expires_at..."
gcloud firestore fields ttls update expires_at \
  --project="$PROJECT_ID" \
  --database="$DB" \
  --collection-group=ground_truth_decisions \
  --enable-ttl

echo "==> Done."
echo "    Seed the first doc in each collection via the Console to make"
echo "    them visible in the explorer — see DEPLOY.md \xC2\xA73b."
