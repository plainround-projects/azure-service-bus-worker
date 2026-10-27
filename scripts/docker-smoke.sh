#!/usr/bin/env bash
# Check the image without Azure: it runs as a non-root user, the simulation (which needs the packaged sql/ scripts)
# reproduces the lesson's failures, and the worker refuses to start without a namespace.
#   scripts/docker-smoke.sh <image>
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need docker

IMAGE="${1:?usage: docker-smoke.sh <image>}"

user_id="$(docker run --rm --entrypoint id "$IMAGE" -u)"
[[ "$user_id" != "0" ]] || die "the container runs as root"
log "container user id: $user_id"

docker run --rm --entrypoint order-simulate "$IMAGE" --expect dirty duplicates --mode naive | tail -3
docker run --rm --entrypoint order-simulate "$IMAGE" --expect clean poison | tail -3

set +e
output="$(docker run --rm "$IMAGE" 2>&1)"
code=$?
set -e
[[ "$code" == "2" ]] || die "expected exit code 2 without configuration, got $code"
grep -q "SB_NAMESPACE" <<<"$output" || die "the configuration error does not name SB_NAMESPACE: $output"
log "OK: non-root, packaged SQL works, and the worker fails fast on missing configuration"
