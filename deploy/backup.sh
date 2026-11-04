#!/bin/sh
# The nightly backup and its monthly proof (LEKA-408), run by the box's
# crontab (docs/operations.md § 4):
#
#   30 3 * * * /opt/leka/backup.sh dump   >> /opt/leka/backup.log 2>&1
#   30 4 1 * * /opt/leka/backup.sh verify >> /opt/leka/backup.log 2>&1
#
# The image is rebuilt first from the API image running now, so the backup
# always runs the code that is deployed — cached, it takes a second. On the
# compose network, with what docker-compose gives the services and
# production.env does not hold: the environment and Redis.
set -eu
cd /opt/leka
case "${1:-}" in
  dump) set -- dump /backups/leka.dump --upload ;;
  verify) set -- verify /backups/leka.dump ;;
  *) echo "usage: $0 dump|verify" >&2; exit 2 ;;
esac
api=$(docker inspect --format '{{.Config.Image}}' leka-api-1)
docker build -q -f backup.Dockerfile --build-arg "API_IMAGE=$api" -t leka-backup . > /dev/null
# Each new API image leaves its layers in the build cache, and nothing else
# empties it on the box: on 2026-11-04 it held about 9 GB of the 19 GB disk.
# What the nightly build reuses was used last night, so it stays.
docker builder prune -f --filter until=48h > /dev/null || true
echo "$(date -u +%FT%TZ) $1 with $api"
exec docker run --rm --network leka_default --env-file production.env \
  -e LEKA_ENVIRONMENT=production -e LEKA_REDIS_URL=redis://redis:6379/0 \
  -v /opt/leka/backups:/backups leka-backup python -m leka.ops.backup "$@"
