#!/usr/bin/env bash
# Create the Artifact Registry Docker repo that holds the agent + MCP
# server container images, and grant Cloud Build the IAM role it needs
# to push to it.
#
# Used by every `gcloud builds submit ... --tag` in the project. Image
# refs look like:
#   ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/<image>:<tag>
#
# Usage:
#   export PROJECT_ID=my-project
#   export REGION=us-central1
#   ./create_artifact_registry.sh
#
# Optional:
#   AR_REPO=agents      # default; the repo name shared by all images
#
# Re-running is safe: existing repo is detected and skipped; IAM
# bindings are idempotent.

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required (export PROJECT_ID=my-project)}"
: "${REGION:?REGION is required (export REGION=us-central1)}"
: "${AR_REPO:=agents}"

echo "==> Project:  $PROJECT_ID"
echo "==> Region:   $REGION"
echo "==> Repo:     $AR_REPO"

# 1. Enable APIs (idempotent).
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  --project="$PROJECT_ID"

# 2. Create the Docker repo. `repositories create` errors if it
#    already exists; swallow that one specific failure.
echo "==> Creating Docker repo $AR_REPO in $REGION..."
gcloud artifacts repositories create "$AR_REPO" \
  --project="$PROJECT_ID" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Container images for the AaaS agents + MCP servers" \
  2>&1 | tee /tmp/ar-create.log || \
  grep -q "ALREADY_EXISTS" /tmp/ar-create.log

# 3. Cloud Build IAM. In projects created after mid-2024, Cloud Build
#    runs as the Compute Engine default SA, which by default has no
#    permission to push to AR (or write build logs / read the staging
#    bucket). One role covers all of them:
#    roles/cloudbuild.builds.builder.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
echo "==> Granting Cloud Build SA ($COMPUTE_SA) roles/cloudbuild.builds.builder..."
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${COMPUTE_SA}" \
  --role="roles/cloudbuild.builds.builder" >/dev/null

echo "==> Done."
echo "    Image refs in this repo look like:"
echo "      ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/<image-name>:<tag>"
echo ""
echo "    Build + push test:"
echo "      gcloud builds submit <path-to-dockerfile-dir> \\"
echo "        --project=$PROJECT_ID \\"
echo "        --tag ${REGION}-docker.pkg.dev/${PROJECT_ID}/${AR_REPO}/example:0.1.0"
