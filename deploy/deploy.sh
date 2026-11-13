#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
: "${GITHUB_SHA:?GITHUB_SHA is required}"
if [[ ! "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "GITHUB_SHA must be a full commit SHA" >&2
  exit 1
fi

export DASHBOARD_IMAGE="ai-quota-dashboard-actions:${GITHUB_SHA}"
compose=(docker compose -f deploy/compose.production.yml)

# Build before replacing the healthy container, and retain its exact image for rollback.
previous_image=$(docker inspect --format '{{.Image}}' ai-quota-dashboard 2>/dev/null || true)
"${compose[@]}" build dashboard
docker run --rm --network none --read-only --tmpfs /tmp:rw,exec,nosuid,nodev \
  -v "$PWD/tests:/tests:ro" -v "$PWD/deploy:/deploy:ro" \
  --entrypoint python "$DASHBOARD_IMAGE" \
  -B -m unittest discover -s /tests -v

if "${compose[@]}" up -d --no-build --wait --wait-timeout 90 dashboard; then
  echo "Deployed ${GITHUB_SHA}"
  exit 0
fi

echo "Deployment failed health checks." >&2
if [[ -n "$previous_image" ]]; then
  echo "Restoring the previous image." >&2
  export DASHBOARD_IMAGE="$previous_image"
  if ! "${compose[@]}" up -d --no-build --wait --wait-timeout 90 dashboard; then
    echo "Rollback failed; inspect the production container." >&2
  fi
fi
exit 1
