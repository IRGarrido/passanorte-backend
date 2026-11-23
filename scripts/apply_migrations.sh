#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -n "${DATABASE_URL_TEMPLATE_FILE:-}" ]]; then
  URL_TEMPLATE="$(cat "$DATABASE_URL_TEMPLATE_FILE")"
else
  URL_TEMPLATE="${DATABASE_URL_TEMPLATE:?Set DATABASE_URL_TEMPLATE_FILE or DATABASE_URL_TEMPLATE}"
fi
if [[ "$URL_TEMPLATE" != *'{svc}'* ]]; then
  echo "Database template must contain {svc}" >&2
  exit 1
fi
for svc in auth catalog chatbot gamification insights notifications validation; do
  echo "Migrating $svc"
  DATABASE_URL="${URL_TEMPLATE/'{svc}'/$svc}" alembic -c "src/services/$svc/alembic.ini" upgrade head
done
