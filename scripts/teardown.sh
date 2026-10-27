#!/usr/bin/env bash
# Destroy everything this project created, including the subscription-scoped budget.
#   scripts/teardown.sh [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login

AUTO_APPROVE=""
[[ "${1:-}" == "--yes" ]] && AUTO_APPROVE="-auto-approve"

RG="$(tf_out resource_group_name)"
terraform -chdir="$TF_DIR" destroy -input=false $AUTO_APPROVE
log "resource group $RG exists? -> $(az group exists --name "$RG")"
log "a Service Bus namespace is deleted at once (it has no soft delete); the Standard tier bills by the hour until then"
