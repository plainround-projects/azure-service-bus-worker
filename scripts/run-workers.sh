#!/usr/bin/env bash
# Lesson step 4: run N workers in parallel on the session queue, from this laptop (az login identity), sharing one ledger.
#   scripts/run-workers.sh 3
# Each worker's log goes to logs/worker-<n>.log, so `grep "out of order" logs/worker-*.log` is the lesson's check.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

COUNT="${1:-3}"
IDLE="${UNTIL_IDLE:-60}"
mkdir -p "$ROOT/logs" "$ROOT/data"
export USE_SESSIONS=1
: "${SB_NAMESPACE:?run: eval \"\$(scripts/env.sh)\"}"

pids=()
cleanup() { kill -TERM "${pids[@]}" 2>/dev/null || true; }
trap cleanup INT TERM

for n in $(seq 1 "$COUNT"); do
  "$ROOT/.venv/bin/order-worker" --until-idle "$IDLE" >"$ROOT/logs/worker-$n.log" 2>&1 &
  pids+=("$!")
  log "worker $n started (pid $!), log: logs/worker-$n.log"
done

status=0
for pid in "${pids[@]}"; do wait "$pid" || status=$?; done
log "all workers finished (exit status $status)"
violations="$(cat "$ROOT"/logs/worker-*.log | grep -c 'out of order' || true)"
log "lines containing 'out of order' in the logs: $violations"
"$ROOT/.venv/bin/order-check"
