#!/usr/bin/env bash
# Deploy the Citibike × Weather dashboard to Google Cloud Run (from source).
#
# Run this from a principal that can deploy to Cloud Run in `nyu-datasets`
# (the pipeline's claude-agent service account cannot — see README.md for the
# exact roles/APIs required). Override any value via the environment, e.g.:
#
#   REGION=us-east1 SERVICE=citibike-weather bash deploy.sh
#
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="${PROJECT:-nyu-datasets}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-citibike-weather-dashboard}"
# Runtime identity for the service. It only needs to READ BigQuery
# (citibike + weather datasets). claude-agent already can; swap in a dedicated
# viewer SA if you prefer least privilege.
RUNTIME_SA="${RUNTIME_SA:-claude-agent@nyu-datasets.iam.gserviceaccount.com}"

echo "Project=$PROJECT  Region=$REGION  Service=$SERVICE  Runtime SA=$RUNTIME_SA"

echo "==> Ensuring required APIs are enabled…"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project "$PROJECT"

echo "==> Deploying to Cloud Run…"
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "BQ_PROJECT=${PROJECT}"

echo "==> Done. Service URL:"
gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" \
  --format="value(status.url)"
