#!/usr/bin/env bash
# deploy.sh — Build arm64 Docker images locally and push to RPi.
# No source code is copied to RPi. It loads and runs pre-built images only.
#
# Usage:
#   ./deploy.sh                  # deploy all services
#   ./deploy.sh dashboard        # deploy one service
#   ./deploy.sh dashboard dns    # deploy multiple services
#
# Prerequisites (first run only):
#   docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
#   docker buildx create --name multiarch --driver docker-container --use

set -e

REMOTE="richard@10.254.254.4"
REMOTE_DIR="~/richsinkhole"
PLATFORM="linux/arm64"
BUILDER="multiarch"
SERVICES=("${@}")

# Default: all services
if [ ${#SERVICES[@]} -eq 0 ]; then
  SERVICES=(dashboard dns updater youtube-proxy unbound)
fi

echo "==> Target: $REMOTE ($PLATFORM)"
echo "==> Services to deploy: ${SERVICES[*]}"
echo ""

for svc in "${SERVICES[@]}"; do
  IMAGE="richsinkhole-${svc}:latest"
  CTX="./${svc}"

  echo "──────────────────────────────────────"
  echo "  Building: $svc  ($PLATFORM)"
  echo "──────────────────────────────────────"
  docker buildx build \
    --builder "$BUILDER" \
    --platform "$PLATFORM" \
    --network host \
    --tag "$IMAGE" \
    --load \
    "$CTX"

  echo "  Transferring image to RPi (no source files)..."
  docker save "$IMAGE" | gzip | ssh "$REMOTE" "docker load"

  echo "  Restarting $svc on RPi..."
  ssh "$REMOTE" "cd $REMOTE_DIR && docker compose up -d $svc"

  echo "  ✓ $svc deployed"
  echo ""
done

echo "==> All done. Verifying on RPi..."
ssh "$REMOTE" "cd $REMOTE_DIR && docker compose ps"

# Restore default builder so local builds stay amd64
DOCKER_DEFAULT_PLATFORM=linux/amd64
export DOCKER_DEFAULT_PLATFORM
