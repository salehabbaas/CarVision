#!/bin/bash
# CarVision Deploy Script
#
# Usage:
#   ./deploy.sh          # auto-detect hard vs soft from git changes
#   ./deploy.sh --hard   # force full teardown + volume wipe
#   ./deploy.sh --soft   # force soft restart (keep volumes)
#
# Hard deploy is triggered automatically when any of these files changed
# since the last deploy: Dockerfile, requirements.txt, docker-compose,
# models.py, db.py, or docker-vpn-routes.sh.

set -euo pipefail

COMPOSE_FILE="docker-compose.carvision.yml"
ENV_FILE=".env.carvision"
VERSION_FILE=".build-version"
LAST_DEPLOY_FILE=".last-deploy-commit"

# Files whose change means images/volumes must be rebuilt from scratch
HARD_TRIGGERS=(
  "Dockerfile"
  "requirements.txt"
  "docker-compose.carvision.yml"
  "docker-vpn-routes.sh"
  "backend/app/models.py"
  "backend/app/db.py"
)

# ── Parse flags ───────────────────────────────────────────────────────────────
MODE="auto"
for arg in "$@"; do
  [[ "$arg" == "--hard" ]] && MODE="hard"
  [[ "$arg" == "--soft" ]] && MODE="soft"
done

# ── Auto-detect hard vs soft from git diff ────────────────────────────────────
if [[ "$MODE" == "auto" ]]; then
  if [[ -f "$LAST_DEPLOY_FILE" ]] && git rev-parse --verify "$(cat "$LAST_DEPLOY_FILE")" &>/dev/null; then
    LAST_COMMIT=$(cat "$LAST_DEPLOY_FILE")
    CHANGED=$(git diff --name-only "$LAST_COMMIT" HEAD 2>/dev/null || true)

    if [[ -z "$CHANGED" ]]; then
      echo "ℹ️  No git changes since last deploy — using soft restart"
      MODE="soft"
    else
      TRIGGER_HIT=""
      for trigger in "${HARD_TRIGGERS[@]}"; do
        if echo "$CHANGED" | grep -qF "$trigger"; then
          TRIGGER_HIT="$trigger"
          break
        fi
      done

      if [[ -n "$TRIGGER_HIT" ]]; then
        echo "📦 Hard trigger detected: $TRIGGER_HIT"
        MODE="hard"
      else
        echo "✏️  Only app/config changes detected — using soft restart"
        MODE="soft"
      fi
    fi
  else
    echo "ℹ️  No previous deploy recorded — using soft (volumes preserved)"
    MODE="soft"
  fi
fi

# ── Version bump ──────────────────────────────────────────────────────────────
[[ -f "$VERSION_FILE" ]] || echo "0" > "$VERSION_FILE"
BUILD_NUM=$(( $(cat "$VERSION_FILE") + 1 ))
echo "$BUILD_NUM" > "$VERSION_FILE"
BUILD_LABEL="v1.$(date '+%Y%m%d').${BUILD_NUM}"

echo ""
echo "🚗 CarVision Deploy — Build ${BUILD_LABEL} [${MODE}] — $(date '+%Y-%m-%d %H:%M:%S')"
echo ""

# ── Bring down ────────────────────────────────────────────────────────────────
if [[ "$MODE" == "hard" ]]; then
  echo "⚠️  Hard reset: removing containers, networks, and volumes..."
  docker compose -f "$COMPOSE_FILE" down --remove-orphans --volumes
else
  echo "🔄 Soft restart: keeping volumes intact..."
  docker compose -f "$COMPOSE_FILE" down --remove-orphans
fi

# ── Build and start ───────────────────────────────────────────────────────────
echo "🔨 Building and starting services..."
BUILD_LABEL="$BUILD_LABEL" docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" up -d --build

# ── Save current commit for next run ─────────────────────────────────────────
git rev-parse HEAD > "$LAST_DEPLOY_FILE" 2>/dev/null || true

echo ""
echo "✅ Build ${BUILD_LABEL} deployed [${MODE}]!"
echo ""
docker compose -f "$COMPOSE_FILE" ps
