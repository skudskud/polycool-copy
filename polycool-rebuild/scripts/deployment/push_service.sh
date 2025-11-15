#!/bin/bash
# Push a specific Polycool service to Railway with the appropriate configuration.
#
# Usage:
#   ./scripts/deployment/push_service.sh api
#   ./scripts/deployment/push_service.sh bot
#   ./scripts/deployment/push_service.sh workers
#   ./scripts/deployment/push_service.sh indexer
#
# Requirements:
#   - Railway CLI must be installed and logged in.
#   - The workspace must already be linked to the cheerful-fulfillment project.

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <api|bot|workers|indexer>"
  exit 1
fi

SERVICE_KEY="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
INDEXER_DIR="/Users/ulyssepiediscalzi/Documents/polynuclear/polycool/apps/subsquid-silo-tests/indexer-ts"

case "${SERVICE_KEY}" in
  api)
    SERVICE_NAME="polycool-api"
    CONFIG_FILE="${ROOT_DIR}/railway.json"
    ;;
  bot)
    SERVICE_NAME="polycool-bot"
    CONFIG_FILE="${ROOT_DIR}/railway.bot.json"
    ;;
  workers)
    SERVICE_NAME="polycool-workers"
    CONFIG_FILE="${ROOT_DIR}/railway.workers.json"
    ;;
  indexer)
    SERVICE_NAME="polycool-indexer"
    CONFIG_FILE="${INDEXER_DIR}/railway.json"
    ;;
  *)
    echo "Unknown service: ${SERVICE_KEY}"
    echo "Supported services: api, bot, workers, indexer"
    exit 1
    ;;
esac

echo "🚀 Deploying service: ${SERVICE_NAME}"

if [[ "${SERVICE_KEY}" == "indexer" ]]; then
  pushd "${INDEXER_DIR}" >/dev/null
  railway up --service "${SERVICE_NAME}"
  popd >/dev/null
  echo "✅ Deployment completed for ${SERVICE_NAME}"
  exit 0
fi

if [[ ! -f "${CONFIG_FILE}" ]]; then
  echo "Configuration file not found: ${CONFIG_FILE}"
  exit 1
fi

TMP_CONFIG="$(mktemp)"
trap 'cp "${TMP_CONFIG}" "${ROOT_DIR}/railway.json"; rm -f "${TMP_CONFIG}"' EXIT

cp "${ROOT_DIR}/railway.json" "${TMP_CONFIG}"
cp "${CONFIG_FILE}" "${ROOT_DIR}/railway.json"

pushd "${ROOT_DIR}" >/dev/null
railway up --service "${SERVICE_NAME}"
popd >/dev/null

echo "✅ Deployment completed for ${SERVICE_NAME}"
