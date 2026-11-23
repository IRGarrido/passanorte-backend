#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for svc in auth catalog gamification benefits insights notifications chatbot; do
  echo "Migrating $svc"
  DATABASE_URL_FILE="${DB_CREDENTIAL_DIR:?}/database-${svc}_migrator" \
    alembic -c "src/services/$svc/alembic.ini" upgrade head
done
