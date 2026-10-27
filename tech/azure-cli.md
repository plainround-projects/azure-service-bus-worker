# Azure CLI

*The commands the scripts use to sign in, read queue properties and build the image. Pinned here: Azure CLI 2.84.0.*

## What it is

The Azure CLI (`az`) is a command-line program for working with Azure. `az login` signs you in. After that commands such as `az group exists` or `az keyvault secret set` call Azure's management and data APIs for you and print the result as text, a table or JSON.

## Why this repository uses it

Terraform creates the resources; the lesson's own steps (queue properties, building the image, finding the identity's object id) are `az` commands. Producing, working and replaying use the Python programs and your `az login` session.

## Where it appears

| File | What it does with it |
|---|---|
| `scripts/provision.sh` | `az provider register`, `az account show`, `az ad signed-in-user show`. |
| `scripts/show-queues.sh` | `az servicebus queue show`. |
| `scripts/build-and-deploy.sh` | `az acr build`, `az acr login`. |
| `scripts/teardown.sh` | `az group exists`. |

## How it works underneath

`az` is a Python program. Commands are grouped by service (`az keyvault`, `az network`) and each takes `--name value` options. `--query` takes a **JMESPath** expression to pick fields out of the JSON result; `--output tsv` prints plain values and `--output table` a table. `az login` stores tokens on your machine; commands then use them. `DefaultAzureCredential` in the app code can borrow that sign-in, which is why the same code runs on a laptop and in Azure.

Two kinds of call exist. **Management plane** calls (create a vault) go to Azure Resource Manager and are authorized by roles such as Contributor. **Data plane** calls (read a secret, list blobs) go to the service itself and need data roles. Being Owner of a resource group does not let you read secrets.

Role assignments and other changes take time to spread, so scripts retry data-plane calls that fail with 403 right after a role was granted.

## Walkthrough of this repository's use

```bash
for provider in Microsoft.App Microsoft.ContainerRegistry Microsoft.Consumption Microsoft.Insights \
  Microsoft.ManagedIdentity Microsoft.OperationalInsights Microsoft.ServiceBus; do
  log "registering $provider"
  az provider register --namespace "$provider" --wait >/dev/null
done
```

Registers each Azure resource provider the project uses (`Microsoft.ServiceBus`, `Microsoft.App`, ...) and waits (`--wait`).

```bash
subscription_id       = "$(az account show --query id --output tsv)"
tenant_id             = "$(az account show --query tenantId --output tsv)"
operator_object_id    = "$(az ad signed-in-user show --query id --output tsv)"
alert_email_addresses = ["$ALERT_EMAIL"]
budget_contact_emails = ["$ALERT_EMAIL"]
```

`--query id --output tsv` selects one field and prints it bare. `az ad signed-in-user show --query id` is your object id, which Terraform needs to grant you the Data Sender and Data Receiver roles.

```bash
  az servicebus queue show --resource-group "$RG" --namespace-name "$NAMESPACE" --name "$queue" \
    --query '{lockDuration:lockDuration, maxDeliveryCount:maxDeliveryCount, requiresSession:requiresSession, active:countDetails.activeMessageCount, deadLetter:countDetails.deadLetterMessageCount}' \
    --output table
```

`az servicebus queue show` reads a queue's properties. The `--query` builds an object from selected fields: `lockDuration` (PT30S, an ISO 8601 duration of 30 seconds), `maxDeliveryCount`, `requiresSession` and the message counts (`countDetails.activeMessageCount`, `countDetails.deadLetterMessageCount`). These are the runbook's signals.

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

`az acr build` builds the image inside the registry; `BUILD_MODE=local` builds with local Docker and pushes after `az acr login`.

### How the Python programs use your login

The producer, the local worker and the replay tool do not call `az` at all. They use `DefaultAzureCredential`, which falls through to the Azure CLI sign-in (see `azure-identity.md`).

## Try it yourself

Check the version.

```bash
az version --query '"azure-cli"' -o tsv
```

You should see something like this:

```text
2.84.0
```

Read the built-in help of a command used by the scripts.

```bash
az servicebus queue show --help 2>&1 | sed -n 1,6p
```

You should see something like this:

```text
Command
    az servicebus queue show : Get a description for the specified queue.

Arguments
```

Without a login this tells you to sign in; with one it prints the subscription.

```bash
az account show 2>&1 | head -2
```

You should see something like this:

```text
ERROR: Please run 'az login' to setup account.
```

## Mistakes people make

- Forgetting `az login`, or being in the wrong subscription (`az account show`).
- Using `--auth-mode key` on a storage account that has shared keys disabled.
- Assuming Owner can read secrets. It cannot; a data role is needed.
- Treating a 403 right after a role assignment as permanent. It can take minutes.
- Parsing table output in scripts. Use `--query` with `--output tsv`.

## Check yourself

1. **What does `--query` take?**
   Answer: A JMESPath expression that selects fields from the JSON result.

2. **What is the difference between management plane and data plane?**
   Answer: Management plane creates and configures resources; data plane reads and writes the data inside them.

3. **Why can an Owner not read a Key Vault secret?**
   Answer: Owner is a management role; reading secrets needs a data role.

4. **What does `az login` do?**
   Answer: Signs you in and stores tokens that later commands use.

5. **How do scripts cope with slow role propagation?**
   Answer: They retry the failing data-plane call for a few minutes.

## Further reading

- Azure CLI 2.84: https://learn.microsoft.com/en-us/cli/azure/
- Query output: https://learn.microsoft.com/en-us/cli/azure/query-azure-cli
