#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for svc in auth catalog gamification benefits insights notifications chatbot; do
  target=head
  if [[ "${1:-}" == "--s2" ]]; then
    case "$svc" in auth|catalog|benefits|gamification|insights|chatbot) target="20261123_${svc}_s2" ;; esac
  elif [[ "${1:-}" == "--s3" ]]; then
    case "$svc" in catalog|benefits) target="20261123_${svc}_s3" ;; gamification) target=20261123_gamification_s2 ;; esac
  fi
  echo "Migrating $svc to $target"
  DATABASE_URL_FILE="${DB_CREDENTIAL_DIR:?}/database-${svc}_migrator" \
    alembic -c "src/services/$svc/alembic.ini" upgrade "$target"
done
