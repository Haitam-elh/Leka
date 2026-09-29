#!/usr/bin/env bash
# Deploy one release of LEKA — the API and the web app, built from the same
# commit — on this machine, prove it came up, and put the previous release
# back if it did not.
#
#   ./deploy.sh <registry> <release>
#   ./deploy.sh ghcr.io/<owner>/leka 3f2c1e9...
#
# The registry holds two images per release, <registry>/api:<release> and
# <registry>/web:<release>. They go out together or not at all: a web app
# a release ahead of its API calls routes that do not exist yet.
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
# THE DISK. Only what runs is kept: the release a failed deployment falls
# back to. Every other image goes BEFORE the pull, and the previous release
# after a success — rolling back to an older one pulls it again. Keeping a
# week of releases, as this did until 2026-09-29, filled the 20 GB disk in
# a week of daily merges (Docker's containerd store holds each image twice,
# packed and unpacked), and the pull died half-way: CD #77.
#
# Assumes the caller is already logged in to the registry.

set -euo pipefail
cd "$(dirname "$0")"

if [ "$#" -ne 2 ]; then
  echo "usage: $0 <registry> <release>" >&2
  exit 2
fi
REGISTRY="$1"
RELEASE="$2"

ENV_FILE="production.env"
COMPOSE=(docker compose -f docker-compose.production.yml --env-file "$ENV_FILE")
# Ninety seconds by default: migrations, a cold start, and room. Past that
# it is not slow, it is broken.
HEALTH_ATTEMPTS="${HEALTH_ATTEMPTS:-45}"
# What pulling a release takes on the disk: both images, packed and
# unpacked — the API's alone is 540 MB unpacked (2026-09-29) — and a margin.
# Below it the pull is not started: one that fills the disk half-way leaves
# it full.
NEEDED_MB="${NEEDED_MB:-2048}"

current() {
  grep -E "^$1=" "$ENV_FILE" | cut -d= -f2- || true
}

# Megabytes free where Docker keeps its images. Nothing when that cannot be
# known — a rehearsal against Docker in a VM — and then nothing is checked.
room_mb() {
  local root
  root="$(docker info --format '{{.DockerRootDir}}' 2> /dev/null)" || return 1
  [ -d "$root" ] || return 1
  df -Pk "$root" | awk 'NR == 2 { print int($4 / 1024) }'
}

# Images no container uses. What runs stays: it is what a failed deployment
# falls back to.
unused_images_go() {
  docker image prune -af > /dev/null || true
}

disk_report() {
  df -h / || true
  docker system df || true
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
#
# The web app is asked from the API's container too: it has curl, and the
# two share the compose network. /login is a page that renders without a
# session, so a 200 means the server is up and serving the build.
healthy() {
  local _
  for _ in $(seq 1 "$HEALTH_ATTEMPTS"); do
    if "${COMPOSE[@]}" exec -T api \
      curl -fsS --max-time 5 http://127.0.0.1:8000/api/v1/health > /dev/null 2>&1 \
      && "${COMPOSE[@]}" exec -T api \
        curl -fsS --max-time 5 http://web:3000/login > /dev/null 2>&1; then
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
  set_var LEKA_REGISTRY "$1"
  set_var LEKA_RELEASE "$2"
  "${COMPOSE[@]}" up -d --remove-orphans
}

PREVIOUS_REGISTRY="$(current LEKA_REGISTRY)"
PREVIOUS="$(current LEKA_RELEASE)"
echo "Previous: ${PREVIOUS:-none}   New: ${RELEASE}"

# Room first, then both pulled before anything is touched: a pull that
# fails leaves the box running as it was.
unused_images_go
if FREE_MB="$(room_mb)" && [ -n "$FREE_MB" ] && [ "$FREE_MB" -lt "$NEEDED_MB" ]; then
  echo "::error::${FREE_MB} MB free on the disk, ${NEEDED_MB} MB needed to pull a release. Nothing was changed. See docs/deployment.md, 'When the disk is full'."
  disk_report
  exit 1
fi

for image in api web; do
  if ! docker pull "${REGISTRY}/${image}:${RELEASE}"; then
    echo "::error::Could not pull ${REGISTRY}/${image}:${RELEASE}. Nothing was changed."
    disk_report
    exit 1
  fi
done

if switch_to "$REGISTRY" "$RELEASE" && healthy; then
  echo "Healthy on ${RELEASE}"
  # The previous release goes now: nothing runs it, and rolling back to it
  # pulls it again. Without -a only untagged layers would go, and every
  # release is tagged.
  unused_images_go
  exit 0
fi

echo "::error::${RELEASE} did not come up."
"${COMPOSE[@]}" ps -a || true
"${COMPOSE[@]}" logs --tail=60 migrate api worker scheduler web || true

if [ -z "$PREVIOUS" ] || [ -z "$PREVIOUS_REGISTRY" ]; then
  echo "::error::No previous release to go back to. The box is down."
  exit 2
fi

# The point of the whole script: a failed deployment does not stay
# deployed. The schema is not rolled back — leka.db.migrate leaves a
# database that is ahead of the image alone (see docs/deployment.md).
echo "Rolling back to ${PREVIOUS}"
if switch_to "$PREVIOUS_REGISTRY" "$PREVIOUS" && healthy; then
  echo "Back on ${PREVIOUS}."
  # Still a failure: the deployment did not happen, and a green tick here
  # would say it did.
  exit 1
fi

echo "::error::Rollback to ${PREVIOUS} did not come up either."
exit 2
