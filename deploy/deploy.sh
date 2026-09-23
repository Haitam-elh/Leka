#!/usr/bin/env bash
# Deploy one release of the LEKA backend on this machine, prove it came up,
# and put the previous release back if it did not.
#
#   ./deploy.sh <image> <release>
#   ./deploy.sh ghcr.io/haitam-elh/leka/api 3f2c1e9...
#
# Run by .github/workflows/cd.yml over SSH, and by a person the same way.
# A file rather than a script inlined in the workflow, so that what CD runs
# is what was rehearsed: the local rehearsal runs this exact file.
#
# Exit status:
#   0  the release is deployed and healthy
#   1  the release is NOT deployed, and the previous one is running
#   2  nothing healthy is running — the box needs a person
#
# Assumes the caller is already logged in to the registry.

set -euo pipefail
cd "$(dirname "$0")"

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <image> <release>" >&2
  exit 2
fi
IMAGE="$1"
RELEASE="$2"

ENV_FILE="staging.env"
COMPOSE=(docker compose -f docker-compose.staging.yml --env-file "$ENV_FILE")
# Ninety seconds by default: migrations, a cold start, and room. Past that
# it is not slow, it is broken.
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-45}"

current() {
  grep -E "^$1=" "$ENV_FILE" | cut -d= -f2- || true
}

set_var() {
  # -i.bak works with both GNU and BSD sed, so the rehearsal on a Mac runs
  # the same line as the box.
  if grep -qE "^$1=" "$ENV_FILE"; then
    sed -i.bak "s|^$1=.*|$1=$2|" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
  else
    echo "$1=$2" >> "$ENV_FILE"
  fi
}

# Running, and still the same process a few seconds later. A container in a
# restart loop is "running" for a moment at a time, and a single look would
# call that up.
steady() {
  local id first second
  id="$("${COMPOSE[@]}" ps -q "$1")"
  [ -n "$id" ] || return 1
  first="$(docker inspect -f '{{.State.Status}} {{.State.StartedAt}}' "$id")"
  sleep 5
  second="$(docker inspect -f '{{.State.Status}} {{.State.StartedAt}}' "$id")"
  [ "$first" = "$second" ] && [ "${first%% *}" = "running" ]
}

# The API is asked directly, inside its own container — not through Caddy.
# Once a domain is set, Caddy answers http://127.0.0.1 with a redirect to
# HTTPS, and curl counts a redirect as a success whether or not anything is
# behind it: the old check reported a dead API as healthy.
healthy() {
  local _
  for _ in $(seq 1 "$HEALTH_ATTEMPTS"); do
    if "${COMPOSE[@]}" exec -T api \
      curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1; then
      # The worker and the scheduler have no endpoint to ask.
      steady worker && steady scheduler
      return
    fi
    sleep 2
  done
  return 1
}

# Called inside `if`, so a failure here — a migration that fails, a
# container that will not start — reaches the rollback below instead of
# stopping the script under `set -e` with the broken release written down
# as the current one.
switch_to() {
  set_var LEKA_IMAGE "$1"
  set_var LEKA_RELEASE "$2"
  "${COMPOSE[@]}" up -d --remove-orphans
}

PREVIOUS_IMAGE="$(current LEKA_IMAGE)"
PREVIOUS="$(current LEKA_RELEASE)"
echo "Previous: ${PREVIOUS:-none}   New: ${RELEASE}"

# Pulled before anything is touched: a pull that fails leaves the box
# exactly as it was.
if ! docker pull "${IMAGE}:${RELEASE}"; then
  echo "::error::Could not pull ${IMAGE}:${RELEASE}. Nothing was changed."
  exit 1
fi

if switch_to "$IMAGE" "$RELEASE" && healthy; then
  echo "Healthy on ${RELEASE}"
  # Images no container uses, built more than a week ago. Without -a only
  # untagged layers go, and every release is tagged: an 8 GB disk fills in
  # about fifteen deployments. The previous release goes too once it is a
  # week old; rolling back to it pulls it again.
  docker image prune -af --filter "until=168h" > /dev/null || true
  exit 0
fi

echo "::error::${RELEASE} did not come up."
"${COMPOSE[@]}" ps -a || true
"${COMPOSE[@]}" logs --tail=60 migrate api worker scheduler || true

if [ -z "$PREVIOUS" ] || [ -z "$PREVIOUS_IMAGE" ]; then
  echo "::error::No previous release to go back to. The box is down."
  exit 2
fi

# The point of the whole script: a failed deployment does not stay
# deployed. The schema is not rolled back — leka.db.migrate leaves a
# database that is ahead of the image alone (see docs/deployment.md).
echo "Rolling back to ${PREVIOUS}"
if switch_to "$PREVIOUS_IMAGE" "$PREVIOUS" && healthy; then
  echo "Back on ${PREVIOUS}."
  # Still a failure: the deployment did not happen, and a green tick here
  # would say it did.
  exit 1
fi

echo "::error::Rollback to ${PREVIOUS} did not come up either."
exit 2
