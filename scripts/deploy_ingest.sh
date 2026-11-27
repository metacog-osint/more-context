#!/usr/bin/env bash
# Deploy the MORE CONTEXT 15-minute ingest to Google Cloud project context-484804.
# Creates: one Cloud Storage bucket, two service accounts, one private Cloud Run function, and one
# Cloud Scheduler job. Run only with approval (it creates billable resources, expected $0-0.10/month).
# Safe to re-run: create steps that already exist print an error and the script continues.
set -u
PROJECT=context-484804
REGION=us-central1
BUCKET=more-context-484804
FN=mc-ingest
RUN_SA=mc-ingest@${PROJECT}.iam.gserviceaccount.com
SCHED_SA=mc-scheduler@${PROJECT}.iam.gserviceaccount.com

# 1. Bucket for cycle output and state (regional, uniform access, no public access).
gcloud storage buckets create gs://${BUCKET} --project=${PROJECT} --location=${REGION} \
  --uniform-bucket-level-access --public-access-prevention

# 2. Service accounts: one the function runs as, one Cloud Scheduler uses to call it.
gcloud iam service-accounts create mc-ingest --project=${PROJECT} --display-name="MORE CONTEXT ingest"
gcloud iam service-accounts create mc-scheduler --project=${PROJECT} --display-name="MORE CONTEXT scheduler"
gcloud storage buckets add-iam-policy-binding gs://${BUCKET} \
  --member=serviceAccount:${RUN_SA} --role=roles/storage.objectAdmin

# 3. The function: private, one instance at a time (state is a single object), 5-minute limit.
gcloud functions deploy ${FN} --gen2 --project=${PROJECT} --region=${REGION} \
  --runtime=python312 --source=. --entry-point=ingest --trigger-http --no-allow-unauthenticated \
  --service-account=${RUN_SA} --memory=512Mi --timeout=300s --max-instances=1 \
  --set-env-vars=MC_BUCKET=${BUCKET}
gcloud functions add-invoker-policy-binding ${FN} --project=${PROJECT} --region=${REGION} \
  --member=serviceAccount:${SCHED_SA}

# 4. One scheduler job, 5 minutes after each GDELT quarter-hour, authenticated with an OIDC token.
URL=$(gcloud functions describe ${FN} --gen2 --project=${PROJECT} --region=${REGION} --format='value(serviceConfig.uri)')
gcloud scheduler jobs create http ${FN}-15min --project=${PROJECT} --location=${REGION} \
  --schedule="5,20,35,50 * * * *" --time-zone=Etc/UTC --uri="${URL}" --http-method=POST \
  --oidc-service-account-email=${SCHED_SA} --oidc-token-audience="${URL}" --attempt-deadline=320s

echo "Deployed. Check: gcloud scheduler jobs list --project=${PROJECT} --location=${REGION}"
