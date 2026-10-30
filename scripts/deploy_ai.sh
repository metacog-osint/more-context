#!/usr/bin/env bash
# Turn on MORE CONTEXT's AI coding under the $5/month cap (pipeline/budget.py). Run only with Tom's yes.
# 1. lets the ingest service account call Vertex AI (alarm coding and the API both run as it)
# 2. redeploys mc-ingest with MC_AI=on (alarm-triggered coding)
# 3. deploys the public API mc-api (anyone may read and request on-view coding; the ledger caps spend)
# Since 30 Oct 2026 both keep the ingest state in Firestore (MC_STATE=firestore, pipeline/statestore.py): the
# service account needs Firestore read/write (roles/datastore.user; (default) database, mc_state collection).
# Cloud Run's free tier covers the API's requests; the only spend is Vertex, capped at $5/month.
set -u
PROJECT=context-484804
REGION=us-central1
BUCKET=more-context-484804
RUN_SA=mc-ingest@${PROJECT}.iam.gserviceaccount.com

gcloud projects add-iam-policy-binding ${PROJECT} \
  --member=serviceAccount:${RUN_SA} --role=roles/aiplatform.user --condition=None
gcloud projects add-iam-policy-binding ${PROJECT} \
  --member=serviceAccount:${RUN_SA} --role=roles/datastore.user --condition=None

gcloud functions deploy mc-ingest --gen2 --project=${PROJECT} --region=${REGION} \
  --runtime=python312 --source=. --entry-point=ingest --trigger-http --no-allow-unauthenticated \
  --service-account=${RUN_SA} --memory=512Mi --timeout=300s --max-instances=1 \
  --set-env-vars=MC_BUCKET=${BUCKET},MC_AI=on,MC_STATE=firestore

gcloud functions deploy mc-api --gen2 --project=${PROJECT} --region=${REGION} \
  --runtime=python312 --source=. --entry-point=api --trigger-http --allow-unauthenticated \
  --service-account=${RUN_SA} --memory=512Mi --timeout=120s --max-instances=1 --concurrency=1 \
  --set-env-vars=MC_BUCKET=${BUCKET},MC_AI=on,MC_STATE=firestore

# Kill switch: redeploy either function with MC_AI=off (or set the cap lower with MC_AI_MONTHLY_CAP_USD).
