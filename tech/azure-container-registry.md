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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/container_registry/main.tf`

18 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 19**

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

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** **Azure role-based access control (RBAC)** decides who may do what. A *role* is a named bundle of permissions (for example "Key Vault Secrets User" may read secrets), a *scope* is where the grant applies (one resource, a resource group, a whole subscription), and a *role assignment* connects an identity, a role and a scope. The smaller the scope, the less a leaked identity can do.

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** A **container registry** is a server that stores container images under names and version tags. **Azure Container Registry (ACR)** is Azure's; a service pulls an image from it using an identity that holds the `AcrPull` role.

**New idea.** A **private endpoint** gives an Azure service (a vault, a storage account) a private IP address inside your subnet, so traffic stays on your private network. For the service's normal name to lead to that private address, a *private DNS zone* (such as `privatelink.vaultcore.azure.net`) must be linked to the network.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_container_registry" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_container_registry.this`. An **Azure Container Registry (ACR)** stores container images and serves them to Azure services that pull them.
- `#checkov:skip=CKV_AZURE_163:vulnerability scanning needs Microsoft Defender for Containers`: A comment of the form `#checkov:skip=RULE:reason` tells the scanner checkov to ignore one rule for this resource and records why. Without the reason the skip is hard to defend in review. Scanner exception for rule `CKV_AZURE_163`: vulnerability scanning needs Microsoft Defender for Containers.
- `#checkov:skip=CKV_AZURE_164:signed images need the Premium SKU`: Scanner exception for rule `CKV_AZURE_164`: signed images need the Premium SKU.
- `#checkov:skip=CKV_AZURE_165:geo-replication needs the Premium SKU`: Scanner exception for rule `CKV_AZURE_165`: geo-replication needs the Premium SKU.
- `#checkov:skip=CKV_AZURE_166:image quarantine needs the Premium SKU`: Scanner exception for rule `CKV_AZURE_166`: image quarantine needs the Premium SKU.
- `#checkov:skip=CKV_AZURE_167:the untagged-manifest retention policy needs the Premium SKU`: Scanner exception for rule `CKV_AZURE_167`: the untagged-manifest retention policy needs the Premium SKU.
- `#checkov:skip=CKV_AZURE_233:zone redundancy needs the Premium SKU`: Scanner exception for rule `CKV_AZURE_233`: zone redundancy needs the Premium SKU.
- `#checkov:skip=CKV_AZURE_237:dedicated data endpoints need the Premium SKU`: Scanner exception for rule `CKV_AZURE_237`: dedicated data endpoints need the Premium SKU.
- `#checkov:skip=CKV_AZURE_139:disabling public access needs the Premium SKU and a private endpoint; the pull is `…: Scanner exception for rule `CKV_AZURE_139`: disabling public access needs the Premium SKU and a private endpoint; the pull is authorized by an identity with AcrPull.
- `name                = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Registry name: 5 to 50 letters and digits, globally unique).
- `resource_group_name = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds the registry).
- `location            = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `sku                 = var.sku`: `sku`: The pricing tier / capability level (the SKU) of the service. Here: the input variable `sku` (Basic is the cheapest tier and enough to build and pull one image).
- `tags                = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to the registry).
- `# No shared admin username and password: images are pulled by an identity holding AcrPull on this registry.`: A line starting with `#` (or `//`) is a **comment**: Terraform ignores it; it is there for the reader. Comment for the reader: No shared admin username and password: images are pulled by an identity holding AcrPull on this registry.
- `admin_enabled          = false`: `admin_enabled`: Whether the registry's shared admin user and password exist. `false` means only identities with roles can use it. Here: `false`.
- `anonymous_pull_enabled = false`: `anonymous_pull_enabled`: Whether anyone can pull images without signing in. Here: `false`.
- Closing line: `}` ends the block opened above.

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
