#!/bin/bash
set -e

# ==============================================================================
# ONESUITE BACKEND DEPLOYMENT SCRIPT
# ==============================================================================
# This script deploys the current code to Google Cloud Run.
# It assumes:
#   1. You are authenticated with `gcloud auth login`.
#   2. You have selected the project with `gcloud config set project [PROJECT_ID]`.
#   3. You have the repo cloned locally.
# ==============================================================================

# ------------------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------------------
# The Google Cloud Project ID
PROJECT_ID="festive-music-484414-v7"

# The region to deploy to
REGION="asia-southeast1"

# The name of the Cloud Run service
SERVICE_NAME="onesuite-backend"

# The connection name of your Cloud SQL instance.
# Format: project-id:region:instance-name
DB_INSTANCE_CONNECTION_NAME="festive-music-484414-v7:asia-southeast1:onesuite-postgres-dev"

# Database Connection Details (passed as env vars)
DB_NAME="onesuite_db"
DB_USER="onesuite_user"
# Note: DB_PASSWORD and SECRET_KEY should be set once manually or via Secret Manager
# to avoid hardcoding them here.

# ------------------------------------------------------------------------------
# SAFETY CHECKS
# ------------------------------------------------------------------------------
if [[ "$PROJECT_ID" == "TODO_YOUR_PROJECT_ID" ]]; then
    echo "ERROR: Please update 'PROJECT_ID' in deploy.sh"
    exit 1
fi

# Load secrets from .env if present (for local runs)
if [ -f .env ]; then
    echo "Loading secrets from .env..."
    export $(grep -v '^#' .env | xargs)
fi

echo "========================================================"
echo "Deploying $SERVICE_NAME to $REGION (Project: $PROJECT_ID)"
echo "========================================================"

# 1. Pull latest code (SKIPPED: Deploying local changes)
# echo "[1/2] Pulling latest code from git..."
# git pull origin main || echo "Git pull failed (maybe no remote?), continuing..."

# 2. Deploy to Cloud Run
echo "[2/2] Deploying to Cloud Run..."
# --source . : Builds the container image from source using Google Cloud Build
# --allow-unauthenticated: Makes the service public (Change if needed)
# --set-env-vars: Configures the app to talk to Cloud SQL via Unix socket
gcloud run deploy "$SERVICE_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --add-cloudsql-instances "$DB_INSTANCE_CONNECTION_NAME" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "DEBUG=False" \
  --set-env-vars "DB_ENGINE=django.db.backends.postgresql" \
  --set-env-vars "DB_NAME=$DB_NAME" \
  --set-env-vars "DB_USER=$DB_USER" \
  --set-env-vars "DB_HOST=/cloudsql/$DB_INSTANCE_CONNECTION_NAME" \
  --set-env-vars "ALLOWED_HOSTS=*" \
  --set-env-vars "DB_PASSWORD=$DB_PASSWORD" \
  --set-env-vars "SECRET_KEY=$SECRET_KEY"

echo "========================================================"
echo "DEPLOYMENT COMPLETE!"
echo "========================================================"
