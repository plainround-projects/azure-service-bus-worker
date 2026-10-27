#!/usr/bin/env bash
# The queue properties the lesson sets (30 s lock, 10 deliveries) and the message counts that are the runbook's signals.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login

RG="$(tf_out resource_group_name)"
NAMESPACE="$(tf_out namespace_name)"
for queue in orders orders-sessions; do
  log "queue $queue"
  az servicebus queue show --resource-group "$RG" --namespace-name "$NAMESPACE" --name "$queue" \
    --query '{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, requiresSession:requiresSession, active:countDetails.activeMessageCount, deadLetter:countDetails.deadLetterMessageCount}' \
    --output table
done
