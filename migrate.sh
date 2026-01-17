#!/bin/bash
set -e

# ==============================================================================
# ONESUITE MIGRATION SCRIPT (Cloud Run Jobs)
# ==============================================================================
# This script runs database migrations (python manage.py migrate)
# using a Cloud Run Job. This ensures the migration runs in the exact same
# environment (Cloud SQL connection, secrets) as the production app
# without requiring a local proxy.
# ==============================================================================

# ------------------------------------------------------------------------------
# CONFIGURATION (Must match deploy.sh)
# ------------------------------------------------------------------------------
PROJECT_ID="festive-music-484414-v7"
REGION="asia-southeast1"
JOB_NAME="onesuite-migrate"
DB_INSTANCE_CONNECTION_NAME="festive-music-484414-v7:asia-southeast1:onesuite-postgres-dev"

DB_NAME="onesuite_db"
DB_USER="onesuite_user"

# Load secrets from .env if present
if [ -f .env ]; then
    echo "Loading secrets from .env..."
    export $(grep -v '^#' .env | xargs)
else
    echo "WARNING: .env file not found. Secrets (DB_PASSWORD, SECRET_KEY) might be missing."
fi

echo "========================================================"
echo "Creating Migration Job for $JOB_NAME in $REGION"
echo "========================================================"

# Create or Update the validation job
# We use --source . to build the exact same code
gcloud run jobs deploy "$JOB_NAME" \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --source . \
  --add-cloudsql-instances "$DB_INSTANCE_CONNECTION_NAME" \
  --set-env-vars "DEBUG=False" \
  --set-env-vars "DB_ENGINE=django.db.backends.postgresql" \
  --set-env-vars "DB_NAME=$DB_NAME" \
  --set-env-vars "DB_USER=$DB_USER" \
  --set-env-vars "DB_HOST=/cloudsql/$DB_INSTANCE_CONNECTION_NAME" \
  --set-env-vars "DB_PASSWORD=$DB_PASSWORD" \
  --set-env-vars "SECRET_KEY=$SECRET_KEY" \
  --command "python" \
  --args "manage.py,migrate"

echo "========================================================"
echo "Executing Migration Job..."
echo "========================================================"

gcloud run jobs execute "$JOB_NAME" --project "$PROJECT_ID" --region "$REGION" --wait

echo "========================================================"
echo "MIGRATION COMPLETE!"
echo "========================================================"
