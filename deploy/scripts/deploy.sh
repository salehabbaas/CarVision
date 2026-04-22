#!/bin/bash
# CarVision Deploy Script
#
# Usage:
#   ./deploy/scripts/deploy.sh          # soft restart (keep volumes)
#   ./deploy/scripts/deploy.sh --soft   # same as default

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

COMPOSE_FILE="${ROOT_DIR}/deploy/compose/docker-compose.carvision.yml"
ENV_FILE="${ROOT_DIR}/.env.carvision"
VERSION_FILE="${ROOT_DIR}/.build-version"
LAST_DEPLOY_FILE="${ROOT_DIR}/.last-deploy-commit"

# ── Parse flags ───────────────────────────────────────────────────────────────
MODE="soft"
for arg in "$@"; do
  if [[ "$arg" != "--soft" ]]; then
    echo "⚠️  Ignoring unknown flag: $arg"
  fi
done

# ── Version bump ──────────────────────────────────────────────────────────────
[[ -f "$VERSION_FILE" ]] || echo "0" > "$VERSION_FILE"
BUILD_NUM=$(( $(cat "$VERSION_FILE") + 1 ))
echo "$BUILD_NUM" > "$VERSION_FILE"
BUILD_LABEL="v1.$(date '+%Y%m%d').${BUILD_NUM}"

echo ""
echo "🚗 CarVision Deploy — Build ${BUILD_LABEL} [${MODE}] — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Bring down (non-destructive) ─────────────────────────────────────────────
echo "🔄 Soft restart: keeping volumes intact..."
docker compose -f "$COMPOSE_FILE" down --remove-orphans

# ── Build and start ───────────────────────────────────────────────────────────
echo "🔨 Building and starting services..."
BUILD_LABEL="$BUILD_LABEL" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

# ── Save current commit for next run ─────────────────────────────────────────
(cd "$ROOT_DIR" && git rev-parse HEAD > "$LAST_DEPLOY_FILE") 2>/dev/null || true

echo ""
echo "✅ Build ${BUILD_LABEL} deployed [${MODE}]!"
echo ""
docker compose -f "$COMPOSE_FILE" ps
