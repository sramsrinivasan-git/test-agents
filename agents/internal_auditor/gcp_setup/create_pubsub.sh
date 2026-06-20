#!/usr/bin/env bash
# Create the Internal Auditor Pub/Sub topic + pull subscription, and
# grant the orchestrator GSA permission to subscribe.
#
# The orchestrator pod opens a streaming pull on the subscription as
# its first action; if the subscription doesn't exist when the pod
# boots, it crash-loops on NotFound. Run this BEFORE applying
# deployment/k8s/deployment.yaml.
#
# Optional DLQ (poison-message handling) is wired in if you set
# CREATE_DLQ=1. It creates a `${TOPIC}-dlq` topic and configures the
# subscription to forward after 5 delivery attempts.
#
# Usage:
#   export PROJECT_ID=my-project
#   export GSA_EMAIL=internal-auditor@${PROJECT_ID}.iam.gserviceaccount.com
#   ./create_pubsub.sh
#
#   # with DLQ:
#   CREATE_DLQ=1 ./create_pubsub.sh
#
# Re-running is safe: existing resources are detected and skipped;
# IAM bindings are idempotent.

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID is required (export PROJECT_ID=my-project)}"
: "${GSA_EMAIL:?GSA_EMAIL is required (export GSA_EMAIL=...)}"
: "${TOPIC:=internal-auditor-triggers}"
: "${SUBSCRIPTION:=${TOPIC}-sub}"
: "${ACK_DEADLINE:=600}"
: "${CREATE_DLQ:=0}"

echo "==> Project:      $PROJECT_ID"
echo "==> Topic:        $TOPIC"
echo "==> Subscription: $SUBSCRIPTION (ack-deadline=${ACK_DEADLINE}s)"
echo "==> GSA:          $GSA_EMAIL"

# 1. Enable the API (idempotent).
gcloud services enable pubsub.googleapis.com --project="$PROJECT_ID"

# 2. Create the trigger topic. `topics create` errors if it already
#    exists; swallow that one specific failure.
echo "==> Creating topic $TOPIC..."
gcloud pubsub topics create "$TOPIC" \
  --project="$PROJECT_ID" 2>&1 | tee /tmp/ps-topic.log || \
  grep -q "Resource already exists" /tmp/ps-topic.log

# 3. (Optional) DLQ topic for messages that fail max delivery attempts.
DLQ_TOPIC="${TOPIC}-dlq"
if [[ "$CREATE_DLQ" == "1" ]]; then
  echo "==> Creating DLQ topic $DLQ_TOPIC..."
  gcloud pubsub topics create "$DLQ_TOPIC" \
    --project="$PROJECT_ID" 2>&1 | tee /tmp/ps-dlq.log || \
    grep -q "Resource already exists" /tmp/ps-dlq.log
fi

# 4. Create the pull subscription. Same swallow-if-exists pattern.
echo "==> Creating subscription $SUBSCRIPTION..."
SUB_ARGS=(
  --project="$PROJECT_ID"
  --topic="$TOPIC"
  --ack-deadline="$ACK_DEADLINE"
  --message-retention-duration=1d
  --expiration-period=never
)
if [[ "$CREATE_DLQ" == "1" ]]; then
  SUB_ARGS+=(
    --dead-letter-topic="$DLQ_TOPIC"
    --max-delivery-attempts=5
  )
fi
gcloud pubsub subscriptions create "$SUBSCRIPTION" \
  "${SUB_ARGS[@]}" 2>&1 | tee /tmp/ps-sub.log || \
  grep -q "Resource already exists" /tmp/ps-sub.log

# 5. Grant the orchestrator GSA roles/pubsub.subscriber on the
#    subscription. add-iam-policy-binding is idempotent.
echo "==> Granting roles/pubsub.subscriber to $GSA_EMAIL on $SUBSCRIPTION..."
gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${GSA_EMAIL}" \
  --role="roles/pubsub.subscriber" >/dev/null

# 6. (DLQ only) Pub/Sub service agent needs publisher on the DLQ topic
#    and subscriber on the source subscription to perform the forwarding.
if [[ "$CREATE_DLQ" == "1" ]]; then
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  PUBSUB_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"
  echo "==> Granting Pub/Sub service agent ($PUBSUB_SA) DLQ permissions..."
  gcloud pubsub topics add-iam-policy-binding "$DLQ_TOPIC" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${PUBSUB_SA}" \
    --role="roles/pubsub.publisher" >/dev/null
  gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" \
    --project="$PROJECT_ID" \
    --member="serviceAccount:${PUBSUB_SA}" \
    --role="roles/pubsub.subscriber" >/dev/null
fi

echo "==> Done."
echo "    Publish a test trigger:"
echo "      gcloud pubsub topics publish $TOPIC \\"
echo "        --project=$PROJECT_ID \\"
echo "        --message='{\"trigger_type\":\"on_demand\",\"lookback_hours\":1.0}'"
