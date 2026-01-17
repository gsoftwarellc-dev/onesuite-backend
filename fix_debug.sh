#!/bin/bash

# Configuration
PROJECT_ID="festive-music-484414-v7"
REGION="asia-southeast1"
JOB_NAME="onesuite-migrate"

echo "========================================================"
echo " INSPECTING & FIXING PERMISSIONS"
echo "========================================================"

# 1. Get Project Number
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

echo "Detected Service Account: $SERVICE_ACCOUNT"

# 2. Grant Cloud SQL Client Role
echo "Granting roles/cloudsql.client to $SERVICE_ACCOUNT..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/cloudsql.client"

echo "========================================================"
echo " RETRYING MIGRATION"
echo "========================================================"

./migrate.sh

echo "========================================================"
echo " DEBUGGING INFO (If it failed again)"
echo "========================================================"
echo "Last 3 Job Execution Errors:"
gcloud run jobs executions list --job $JOB_NAME --region $REGION --limit 3 --format="table(name, status, creationTimestamp, cancelled, logUri)"
