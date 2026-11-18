#!/usr/bin/env bash
# Scalability layer: Pub/Sub topic + Cloud Workflows (Human Gates) + Eventarc trigger.
# Run AFTER the Cloud Run service "war-room" is deployed. Idempotent ("|| true" on create steps).
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project)}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="${CLOUD_RUN_SERVICE:-war-room}"
TOPIC="auditbridge-case-evaluated"
WORKFLOW="auditbridge-gates"
WF_SA="sa-workflows@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud services enable pubsub.googleapis.com workflows.googleapis.com workflowexecutions.googleapis.com \
  eventarc.googleapis.com --project="${PROJECT_ID}"

RUN_URL="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format='value(status.url)')"
echo ">>> Cloud Run URL: ${RUN_URL}"

# 1. Pub/Sub topic (Cloud Run publishes one message per evaluated invoice)
gcloud pubsub topics create "${TOPIC}" --project="${PROJECT_ID}" || true

# 2. Least-privilege service account for the workflow
gcloud iam service-accounts create sa-workflows --display-name="AuditBridge Workflows" --project="${PROJECT_ID}" || true
for ROLE in roles/workflows.invoker roles/run.invoker roles/logging.logWriter roles/eventarc.eventReceiver; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" --member="serviceAccount:${WF_SA}" --role="${ROLE}" >/dev/null
done

# 3. Cloud Run runtime SA may publish to the topic
RUN_SA="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" --format='value(spec.template.spec.serviceAccountName)')"
RUN_SA="${RUN_SA:-$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')-compute@developer.gserviceaccount.com}"
gcloud pubsub topics add-iam-policy-binding "${TOPIC}" --project="${PROJECT_ID}" \
  --member="serviceAccount:${RUN_SA}" --role="roles/pubsub.publisher" >/dev/null

# 4. Deploy the workflow
gcloud workflows deploy "${WORKFLOW}" --location="${REGION}" --project="${PROJECT_ID}" \
  --source=infra/workflow_auditbridge.yaml --service-account="${WF_SA}" \
  --set-env-vars="AUDITBRIDGE_URL=${RUN_URL}"

# 5. Eventarc: Pub/Sub message -> new workflow execution
gcloud eventarc triggers create auditbridge-case-trigger --location="${REGION}" --project="${PROJECT_ID}" \
  --destination-workflow="${WORKFLOW}" --destination-workflow-location="${REGION}" \
  --event-filters="type=google.cloud.pubsub.topic.v1.messagePublished" \
  --transport-topic="projects/${PROJECT_ID}/topics/${TOPIC}" \
  --service-account="${WF_SA}" || true

# 6. Turn publishing on in Cloud Run
gcloud run services update "${SERVICE}" --region="${REGION}" --project="${PROJECT_ID}" \
  --update-env-vars="PUBSUB_TOPIC=${TOPIC}"

echo ">>> Done. Executions: https://console.cloud.google.com/workflows/workflow/${REGION}/${WORKFLOW}/executions?project=${PROJECT_ID}"
