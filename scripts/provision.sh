#!/usr/bin/env bash
# Phase 1: resource group, workspace, identities, Service Bus namespace and queues, registry, role assignments, alert,
# budget. The worker's container app comes in phase 2 (build-and-deploy.sh) because its image must exist first.
#
#   ALERT_EMAIL=you@example.com scripts/provision.sh [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login

AUTO_APPROVE=""
[[ "${1:-}" == "--yes" ]] && AUTO_APPROVE="-auto-approve"

# Register the resource providers once, so the Terraform plan never changes subscription-wide settings itself.
for provider in Microsoft.App Microsoft.ContainerRegistry Microsoft.Consumption Microsoft.Insights \
  Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.ServiceBus; do
  log "registering $provider"
  az provider register --namespace "$provider" --wait >/dev/null
done

TFVARS="$TF_DIR/terraform.tfvars"
if [[ ! -f "$TFVARS" ]]; then
  [[ -n "${ALERT_EMAIL:-}" ]] || die "set ALERT_EMAIL=you@example.com (budget and dead-letter alerts go there), or write $TFVARS yourself"
  log "writing $TFVARS from your az session (it holds ids, so it is git-ignored)"
  cat >"$TFVARS" <<TFVARS_EOF
subscription_id       = "$(az account show --query id --output tsv)"
tenant_id             = "$(az account show --query tenantId --output tsv)"
operator_object_id    = "$(az ad signed-in-user show --query id --output tsv)"
alert_email_addresses = ["$ALERT_EMAIL"]
budget_contact_emails = ["$ALERT_EMAIL"]
budget_start_date     = "$(date -u +%Y-%m-01T00:00:00Z)"
TFVARS_EOF
fi

terraform -chdir="$TF_DIR" init -input=false
terraform -chdir="$TF_DIR" apply -input=false $AUTO_APPROVE

"$ROOT/scripts/show-queues.sh"
log "phase 1 done. Export the settings with: eval \"\$(scripts/env.sh)\"   then: make produce, make worker"
