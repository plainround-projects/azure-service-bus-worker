#!/usr/bin/env bash
# Print the settings the local programs need, from the Terraform outputs. Use: eval "$(scripts/env.sh)"
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need terraform

echo "export SB_NAMESPACE=$(tf_out servicebus_namespace)"
echo "export LEDGER_PATH=$ROOT/data/orders.db"
# AZURE_CLIENT_ID is deliberately not exported: on a laptop the programs use your az login session.
