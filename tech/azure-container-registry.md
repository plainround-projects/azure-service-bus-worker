# Azure Container Registry

*Stores the app image and lets the pull identity fetch it. Pinned here: ACR Basic.*

## What it is

Azure Container Registry (ACR) stores container images privately. An image name has the form `<registry>.azurecr.io/<repository>:<tag>`. Azure Container Apps pulls the image from here when it starts a replica.

## Why this repository uses it

Container Apps need an image to pull. The registry is created first, the image is built into it, then the app is added.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/container_registry/` | The registry. |
| `scripts/build-and-deploy.sh` | Builds with `az acr build`, or locally and pushes. |

## How it works underneath

Pushing and pulling are authenticated. The registry's **admin user** (a shared username and password) is switched off here; instead an identity holds the `AcrPull` role on the registry, and the container app is told to pull with that identity. `az acr build` uploads the source and builds the image inside the registry (**ACR Tasks**), so no local Docker is needed. The Basic tier is the cheapest and billed per day.

## Walkthrough of this repository's use

```hcl
resource "azurerm_container_registry" "this" {
  #checkov:skip=CKV_AZURE_163:vulnerability scanning needs Microsoft Defender for Containers
  #checkov:skip=CKV_AZURE_164:signed images need the Premium SKU
  #checkov:skip=CKV_AZURE_165:geo-replication needs the Premium SKU
  #checkov:skip=CKV_AZURE_166:image quarantine needs the Premium SKU
  #checkov:skip=CKV_AZURE_167:the untagged-manifest retention policy needs the Premium SKU
  #checkov:skip=CKV_AZURE_233:zone redundancy needs the Premium SKU
  #checkov:skip=CKV_AZURE_237:dedicated data endpoints need the Premium SKU
  #checkov:skip=CKV_AZURE_139:disabling public access needs the Premium SKU and a private endpoint; the pull is authorized by an identity with AcrPull
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = var.sku
  tags                = var.tags

  # No shared admin username and password: images are pulled by an identity holding AcrPull on this registry.
  admin_enabled          = false
  anonymous_pull_enabled = false
}
```

`admin_enabled = false` turns off the shared admin password. `anonymous_pull_enabled = false` forbids pulls without credentials. `sku` defaults to `Basic`.

```bash
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
```

`az acr build --registry NAME --image repo:tag DIR` uploads the source and builds in the registry. If ACR Tasks is not allowed on the subscription, `BUILD_MODE=local` builds with local Docker (`--platform linux/amd64` because Azure runs Intel images) and pushes.

## Try it yourself

Run the module's tests.

```bash
cd infra/modules/container_registry && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -4
```

You should see something like this:

```text
tests/container_registry.tftest.hcl... tearing down
tests/container_registry.tftest.hcl... pass

Success! 2 passed, 0 failed.
```

## Mistakes people make

- Enabling the admin user, which is a shared password.
- Pulling `:latest`, which can change under a running service. The module refuses it.
- Giving the app's own identity the pull role; a separate identity keeps its roles minimal.
- Assuming ACR Tasks works on every subscription (free trials may block it); `BUILD_MODE=local` builds with Docker instead.
- Forgetting that the registry bills per day while it exists.

## Check yourself

1. **What does an image name contain?**
   Answer: The registry host, the repository and a tag.

2. **What does `AcrPull` allow?**
   Answer: Pulling images from the registry.

3. **Why disable the admin user?**
   Answer: It is one shared password for everything.

4. **What does `az acr build` do?**
   Answer: Builds the image inside the registry from uploaded source.

5. **Why refuse `:latest`?**
   Answer: It names no fixed version.

## Further reading

- Azure Container Registry: https://learn.microsoft.com/en-us/azure/container-registry/container-registry-intro
- ACR Tasks: https://learn.microsoft.com/en-us/azure/container-registry/container-registry-tasks-overview
