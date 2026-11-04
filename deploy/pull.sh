#!/bin/sh
# Brings one environment of CARO to the images its tags name now
# (docs/PHASE1_SETUP.md): the workflow moves :staging on every merge into
# main and :production on every release tag; this pulls them and starts
# what changed. Run on the server every minute by caro-pull@<env>.timer;
# nothing reaches the server to deploy, the server asks.
#
#   deploy/pull.sh staging
#   deploy/pull.sh production
set -eu
ENV=${1:-}
case "$ENV" in
    production|staging) ;;
    *) echo "usage: deploy/pull.sh production|staging" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.."
FILE=/etc/caro/$ENV.env
[ -r "$FILE" ] || { echo "pull: $FILE is missing; docs/PHASE1_SETUP.md says what it holds" >&2; exit 2; }
C="docker compose -p caro-$ENV --env-file $FILE -f compose.vps.yml"
$C pull --quiet
before=$($C ps -q api 2>/dev/null || true)
$C up -d --remove-orphans --quiet-pull
after=$($C ps -q api 2>/dev/null || true)
# A new API container is a new image or a new env file: what the edge kept
# of the old one is purged (scripts/edge_purge.py), and a failure to purge
# does not undo the deploy -- a kept answer then lives out CARO_EDGE_TTL.
if [ "$before" != "$after" ]; then
    $C --profile purge run --rm edge-purge || true
fi
