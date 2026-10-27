#!/usr/bin/env bash
# Phase 2 (the managed-identity path): build the worker image inside the registry, then add the container app.
#   scripts/build-and-deploy.sh                    az acr build (ACR Tasks)
#   BUILD_MODE=local scripts/build-and-deploy.sh   docker build and push, for subscriptions where ACR Tasks is not allowed
#   TF_VAR_worker_queue=orders-sessions TF_VAR_worker_use_sessions=true scripts/build-and-deploy.sh   (the session queue)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
need az terraform
require_login

REGISTRY="$(tf_out registry_name)"
LOGIN_SERVER="$(tf_out registry_login_server)"
IMAGE="$LOGIN_SERVER/azure-service-bus-worker:$APP_VERSION"

if [[ "${BUILD_MODE:-acr}" == "local" ]]; then
  need docker
  log "building $IMAGE locally and pushing it"
  az acr login --name "$REGISTRY"
  docker build --platform linux/amd64 --tag "$IMAGE" "$ROOT"
  docker push "$IMAGE"
else
  log "building $IMAGE in $REGISTRY"
  az acr build --registry "$REGISTRY" --image "azure-service-bus-worker:$APP_VERSION" "$ROOT"
fi

terraform -chdir="$TF_DIR" apply -input=false -auto-approve -var "deploy_worker=true" -var "image=$IMAGE"

APP="$(tf_out worker_app_name)"
RG="$(tf_out resource_group_name)"
log "worker deployed. Logs: az containerapp logs show --resource-group $RG --name $APP --follow"
log "Ledger check inside the replica: az containerapp exec --resource-group $RG --name $APP --command 'order-check'"
