#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:-$(gcloud config get-value project)}"
REGION="${GCP_REGION:-europe-west1}"
BUCKET="war-room-quarantine-${PROJECT_ID}"
DATASET="war_room"

echo ">>> Bootstrapping Deloitte x GCP War Room in project: ${PROJECT_ID} (${REGION})"

# 1. Enable required GCP APIs
gcloud services enable \
  aiplatform.googleapis.com \
  run.googleapis.com \
  storage.googleapis.com \
  bigquery.googleapis.com \
  firestore.googleapis.com \
  dlp.googleapis.com \
  cloudkms.googleapis.com \
  iamcredentials.googleapis.com \
  cloudtrace.googleapis.com \
  --project="${PROJECT_ID}"

# 2. Create GCS Quarantine Bucket
gsutil mb -p "${PROJECT_ID}" -l "${REGION}" "gs://${BUCKET}" || true

# 3. Create BigQuery Dataset & Audit Table
bq --location="${REGION}" mk -d "${PROJECT_ID}:${DATASET}" || true
bq mk --table "${PROJECT_ID}:${DATASET}.audit_logs" \
  event_id:STRING,timestamp:TIMESTAMP,deal_id:STRING,agent_name:STRING,event_type:STRING,severity:STRING,details_json:STRING || true

# 4. Create 3 Least-Privilege Service Accounts
for SA in sa-legal sa-quant sa-forensic; do
  gcloud iam service-accounts create "${SA}" \
    --display-name="War Room ${SA}" \
    --project="${PROJECT_ID}" || true
done

# sa-legal: Firestore + Vertex AI only (NO BigQuery)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-legal@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer" >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-legal@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" >/dev/null

# sa-quant: BigQuery + Vertex AI only (NO Firestore/GCS)
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-quant@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer" >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-quant@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser" >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-quant@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" >/dev/null

# sa-forensic: Firestore + Vertex AI only
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-forensic@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/datastore.viewer" >/dev/null
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:sa-forensic@${PROJECT_ID}.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user" >/dev/null

echo ">>> Setup complete! Copy .env.example to .env and set GCP_PROJECT_ID=${PROJECT_ID}."
