# Azure Container Apps (the worker)

*Runs the worker image with the managed identity attached. Pinned here: azurerm_container_app (azurerm 4.81).*

## What it is

Azure Container Apps runs containers without you managing servers or Kubernetes. A **Container Apps environment** is the shared boundary (networking and logging) for one or more **container apps**. Each app has one or more **replicas** (running copies), an optional **ingress** (a public HTTPS address), and **probes** that check health.

## Why this repository uses it

The lesson needs a worker that authenticates with a managed identity. The container app is that host: it attaches the identity and runs the image with no ingress.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/worker_app/` | The environment and the app. |
| `infra/environments/dev/main.tf` | Passes the settings as environment variables. |

## How it works underneath

When a replica starts, the platform pulls the image (using the registry identity), starts the container with the environment variables you set, and waits for the **startup probe**. A **liveness probe** that fails makes the platform restart the replica; a **readiness probe** that fails stops traffic being sent to it. With `min_replicas = 0` the app **scales to zero** when idle and the first request pays a cold start.

A container app can have identities attached; the code gets tokens from them. Environment variables are plain text visible in the app's configuration, which is why no secret goes there. Console output goes to the environment's Log Analytics workspace. Ephemeral volumes (`EmptyDir`) live only as long as the replica.

## Walkthrough of this repository's use

```hcl
  identity {
    type         = "UserAssigned"
    identity_ids = [var.worker_identity_id, var.pull_identity_id]
  }

  registry {
    server   = var.registry_server
    identity = var.pull_identity_id
  }

  # No ingress block: the worker is not reachable from outside. Only the platform's probes reach the health port.

  template {
    min_replicas = var.replicas
    max_replicas = var.replicas

    # The SQLite ledger lives here. It is wiped when a replica is replaced, which is fine for a teaching ledger and
    # wrong for production (see ARCHITECTURE.md, "Limits of the teaching build").
    volume {
      name         = "ledger"
      storage_type = "EmptyDir"
    }

    container {
      name   = "worker"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      volume_mounts {
        name = "ledger"
        path = var.ledger_directory
      }

      # Plain environment variables only. There is deliberately no `secret` block and no `secret_name` here.
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/ready"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      startup_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 3
        failure_count_threshold = 10
      }
    }
  }
```

Both identities are attached. The `registry` block says to pull with the pull identity. There is no `ingress` block: the worker only pulls from the queue and cannot be called from outside.

```hcl
    volume {
      name         = "ledger"
      storage_type = "EmptyDir"
    }

    container {
      name   = "worker"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      volume_mounts {
        name = "ledger"
        path = var.ledger_directory
      }

      # Plain environment variables only. There is deliberately no `secret` block and no `secret_name` here.
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      readiness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/ready"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      startup_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 3
        failure_count_threshold = 10
      }
    }
```

An `EmptyDir` volume mounted at `/data` holds the SQLite ledger. It lives as long as the replica; with more than one replica each has its own ledger, which is why `replicas` defaults to 1 and the cross-instance ordering check is run from a laptop (`make workers`).

```hcl
      liveness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 15
        failure_count_threshold = 3
      }
```

Container Apps probes can only call HTTP or TCP, so the worker serves `/live` and `/ready` on port 8080 (see `python.md`). Liveness fails when the receive loop stops making progress; readiness also needs the ledger to answer.

```hcl
  env = {
    AZURE_CLIENT_ID      = module.worker_identity.client_id
    SB_NAMESPACE         = module.servicebus.fully_qualified_namespace
    SB_QUEUE             = var.worker_queue
    USE_SESSIONS         = var.worker_use_sessions ? "1" : "0"
    MODE                 = var.worker_mode
    LOCK_RENEWAL_SECONDS = tostring(var.worker_lock_renewal_seconds)
    SLOW_EVERY           = tostring(var.worker_slow_every)
    HEALTH_PORT          = "8080"
    LEDGER_PATH          = "/data/orders.db"
    SQL_DIR              = "/app/sql"
    LOG_LEVEL            = "INFO"
  }
```

The settings: the identity's client id, the namespace host name, the queue, session mode, the worker mode, lock renewal, the chaos setting, the health port, the ledger path and the SQL folder. There is no key or connection string, and the module would refuse one.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `infra/modules/worker_app/main.tf`

74 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 7**

```hcl
resource "azurerm_container_app_environment" "this" {
  name                       = var.environment_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

**New idea.** **Azure Key Vault** stores secrets, keys and certificates behind Azure's access control and writes an audit record of every use. A program reads a secret by calling the vault with its identity, so the secret never has to sit in a file or in the program's settings.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

**New idea.** **Log Analytics** is Azure's store for logs and metrics, queried with the Kusto Query Language (KQL). A *diagnostic setting* tells a resource to send its logs there, so that, for example, every refused request to a vault can be found afterwards.

**New idea.** An Azure **resource group** is a folder-like container for the resources of one project. Resources in a group share a life cycle: deleting the group deletes everything in it.

**New idea.** **Tags** are name/value labels attached to Azure resources. They change no behavior; they record the owner, project and environment and make cost reports and clean-up possible.

**New idea.** An Azure **region** (such as `westeurope`) is a group of data centers in one geographic area. Where a resource is created decides its latency, its price and which legal rules apply.

- `resource "azurerm_container_app_environment" "this" {`: A `resource` block declares one real thing Terraform must create and keep in step with this file. It has two labels: the **type** (such as `azurerm_key_vault`, which names the provider and the kind of thing) and a **local name** (such as `this`) used only to refer to it from other places as `azurerm_key_vault.this`. The lines inside are the thing's settings, called **arguments**. Declares the resource `azurerm_container_app_environment.this`. A **Container Apps environment** is the shared boundary (network and log destination) that a group of container apps runs inside.
- `name                       = var.environment_name`: `name`: The name of this thing in Azure. Here: the input variable `environment_name` (Container Apps environment name).
- `resource_group_name        = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds both).
- `location                   = var.location`: `location`: The Azure region (data center area) where the thing is created. Here: the input variable `location` (Azure region).
- `log_analytics_workspace_id = var.log_analytics_workspace_id`: `log_analytics_workspace_id`: The id of the Log Analytics workspace that receives the data. Here: the input variable `log_analytics_workspace_id` (Workspace that receives the console logs).
- `tags                       = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to both resources).
- Closing line: `}` ends the block opened above.

**Lines 9 to 28**

```hcl
resource "azurerm_container_app" "this" {
  name                         = var.name
  resource_group_name          = var.resource_group_name
  container_app_environment_id = azurerm_container_app_environment.this.id
  revision_mode                = "Single"
  tags                         = var.tags

  # Two identities, two jobs: the worker identity is what DefaultAzureCredential uses (named by AZURE_CLIENT_ID) and
  # holds only the Service Bus Data Receiver role; the pull identity only pulls the image.
  identity {
    type         = "UserAssigned"
    identity_ids = [var.worker_identity_id, var.pull_identity_id]
  }

  registry {
    server   = var.registry_server
    identity = var.pull_identity_id
  }

  # No ingress block: the worker is not reachable from outside. Only the platform's probes reach the health port.
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

**New idea.** **TLS** is the protocol that encrypts a network connection and proves who is on the other end, which is what the `s` in `https` stands for. The server proves its identity with a **certificate**, a signed document that names the server and carries its public key; a client refuses a certificate it cannot trust.

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

**New idea.** **Azure role-based access control (RBAC)** decides who may do what. A *role* is a named bundle of permissions (for example "Key Vault Secrets User" may read secrets), a *scope* is where the grant applies (one resource, a resource group, a whole subscription), and a *role assignment* connects an identity, a role and a scope. The smaller the scope, the less a leaked identity can do.

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** A **container registry** is a server that stores container images under names and version tags. **Azure Container Registry (ACR)** is Azure's; a service pulls an image from it using an identity that holds the `AcrPull` role.

- `resource "azurerm_container_app" "this" {`: Declares the resource `azurerm_container_app.this`. A **container app** runs a container image as a managed service: Azure supplies the servers, scaling, HTTPS endpoint and revision handling.
- `name                         = var.name`: `name`: The name of this thing in Azure. Here: the input variable `name` (Container app name, for example ca-orders-worker).
- `resource_group_name          = var.resource_group_name`: `resource_group_name`: The resource group the thing is created in. Here: the input variable `resource_group_name` (Resource group that holds both).
- `container_app_environment_id = azurerm_container_app_environment.this.id`: `container_app_environment_id`: The id of the environment this app runs in. Here: the `id` of the resource `azurerm_container_app_environment.this`.
- `revision_mode                = "Single"`: `revision_mode`: How new versions are rolled out. `Single` keeps one active revision and replaces it. Here: the text `"Single"`.
- `tags                         = var.tags`: `tags`: Tags are name/value labels attached to the thing. They do not change behavior; they identify the owner, project and environment and make cost reports readable. Here: the input variable `tags` (Tags applied to both resources).
- `# Two identities, two jobs: the worker identity is what DefaultAzureCredential uses (named by AZURE_CLIENT_ID)`…: A line starting with `#` (or `//`) is a **comment**: Terraform ignores it; it is there for the reader. Comment for the reader: Two identities, two jobs: the worker identity is what DefaultAzureCredential uses (named by AZURE_CLIENT_ID) and
- `# holds only the Service Bus Data Receiver role; the pull identity only pulls the image.`: Comment for the reader: holds only the Service Bus Data Receiver role; the pull identity only pulls the image.
- `identity {`: Starts the nested `identity` block: Attaches an identity to the resource.
- `type         = "UserAssigned"`: `type`: The kind of identity or setting (for an identity: `UserAssigned`). Here: the text `"UserAssigned"`.
- `identity_ids = [var.worker_identity_id, var.pull_identity_id]`: `identity_ids`: The ids of the user-assigned identities attached to this resource. Here: the input variable `worker_identity_id` (Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)), the input variable `pull_identity_id` (Resource id of the identity that only pulls the image (AcrPull on the registry)).
- `registry {`: Starts the nested `registry` block: Tells the app which container registry to pull from and which identity to pull with.
- `server   = var.registry_server`: `server`: The host name of the registry. Here: the input variable `registry_server` (Registry host, for example myregistry.azurecr.io).
- `identity = var.pull_identity_id`: `identity`: The resource id of the identity used to authenticate to the registry (no password involved). Here: the input variable `pull_identity_id` (Resource id of the identity that only pulls the image (AcrPull on the registry)).
- `# No ingress block: the worker is not reachable from outside. Only the platform's probes reach the health port`…: Comment for the reader: No ingress block: the worker is not reachable from outside. Only the platform's probes reach the health port.
- Closing lines: `}` end the blocks opened above.

**Lines 30 to 39**

```hcl
  template {
    min_replicas = var.replicas
    max_replicas = var.replicas

    # The SQLite ledger lives here. It is wiped when a replica is replaced, which is fine for a teaching ledger and
    # wrong for production (see ARCHITECTURE.md, "Limits of the teaching build").
    volume {
      name         = "ledger"
      storage_type = "EmptyDir"
    }
```

- `template {`: Starts the nested `template` block: Describes the running containers and scaling of the app.
- `min_replicas = var.replicas`: `min_replicas`: The fewest copies of the container that run. `0` lets the app scale to zero when idle. Here: the input variable `replicas` (Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)).
- `max_replicas = var.replicas`: `max_replicas`: The most copies Azure may start under load. Here: the input variable `replicas` (Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)).
- `# The SQLite ledger lives here. It is wiped when a replica is replaced, which is fine for a teaching ledger an`…: Comment for the reader: The SQLite ledger lives here. It is wiped when a replica is replaced, which is fine for a teaching ledger and
- `# wrong for production (see ARCHITECTURE.md, "Limits of the teaching build").`: Comment for the reader: wrong for production (see ARCHITECTURE.md, "Limits of the teaching build").
- `volume {`: Starts the nested `volume` block: A storage volume the container can use.
- `name         = "ledger"`: `name`: The name of this thing in Azure. Here: the text `"ledger"`.
- `storage_type = "EmptyDir"`: `storage_type`: How the volume is stored. Here: the text `"EmptyDir"`.
- Closing line: `}` ends the block opened above.

**Lines 41 to 67**

```hcl
    container {
      name   = "worker"
      image  = var.image
      cpu    = var.cpu
      memory = var.memory

      volume_mounts {
        name = "ledger"
        path = var.ledger_directory
      }

      # Plain environment variables only. There is deliberately no `secret` block and no `secret_name` here.
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      liveness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 15
        failure_count_threshold = 3
      }
```

**New idea.** **HTTP** is the protocol of the web. A client sends a *request* (a method such as GET or POST, a path, headers and sometimes a body) and the server sends back a *response* with a three-digit **status code**: 200 means success, 201 created, 400 the request was bad, 403 forbidden, 404 not found, 413 too large, 502 a server behind this one failed.

**New idea.** A **hash** (or *digest*) is a fixed-length fingerprint calculated from some data. The same data always gives the same hash and any change gives a different one, so comparing hashes shows whether a file or an image is exactly the one that was reviewed.

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

- `container {`: Starts the nested `container` block: One container of the app.
- `name   = "worker"`: `name`: The name of this thing in Azure. Here: the text `"worker"`.
- `image  = var.image`: `image`: The container image to run, as `registry/name:tag`. Here: the input variable `image` (Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest).
- `cpu    = var.cpu`: `cpu`: How many CPU cores each copy gets. Here: the input variable `cpu` (vCPU per replica).
- `memory = var.memory`: `memory`: How much memory each copy gets. Here: the input variable `memory` (Memory per replica; Container Apps pairs 0.25 vCPU with 0.5Gi).
- `volume_mounts {`: Starts the nested `volume_mounts` block: Where a volume appears inside the container.
- `name = "ledger"`: `name`: The name of this thing in Azure. Here: the text `"ledger"`.
- `path = var.ledger_directory`: `path`: The folder inside the container where the volume appears. Here: the input variable `ledger_directory` (Directory where the ephemeral volume is mounted; the worker's LEDGER_PATH points into it).
- `# Plain environment variables only. There is deliberately no `secret` block and no `secret_name` here.`: Comment for the reader: Plain environment variables only. There is deliberately no `secret` block and no `secret_name` here.
- `dynamic "env" {`: A `dynamic` block repeats a nested block once for each entry of a collection (`for_each`); `content { ... }` is the block to repeat, and the loop variable is named after the dynamic block. Repeats the nested block `env` once for each entry of the collection named by `for_each`.
- `for_each = var.env`: `for_each` makes one copy of the resource (or module) for each entry of a map or set. Inside, `each.key` is the entry's key and `each.value` its value. Each copy is tracked under its key, so adding or removing one entry touches only that copy. `for_each` is set to the input variable `env` (Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value).
- `content {`: Starts the nested `content` block: The body of the block repeated by the `dynamic` block.
- `name  = env.key`: `name`: The name of this thing in Azure. Here: `env.key`.
- `value = env.value`: `value`: The value of the setting or output. Here: `env.value`.
- `liveness_probe {`: Starts the nested `liveness_probe` block: A health check; if it keeps failing, Azure restarts the container.
- `transport               = "HTTP"`: `transport`: The protocol the probe uses (`HTTP`). Here: the text `"HTTP"`.
- `port                    = var.health_port`: `port`: The port the probe or rule applies to. Here: the input variable `health_port` (Port of the worker's health endpoint (/live and /ready); the platform's probes call it).
- `path                    = "/live"`: `path`: The web path the probe requests. Here: the text `"/live"`.
- `interval_seconds        = 15`: `interval_seconds`: Seconds between probe attempts. Here: the number `15`.
- `failure_count_threshold = 3`: `failure_count_threshold`: How many failed attempts in a row count as unhealthy. Here: the number `3`.
- Closing lines: `}` end the blocks opened above.

**Lines 69 to 84**

```hcl
      readiness_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/ready"
        interval_seconds        = 15
        failure_count_threshold = 3
      }

      startup_probe {
        transport               = "HTTP"
        port                    = var.health_port
        path                    = "/live"
        interval_seconds        = 3
        failure_count_threshold = 10
      }
    }
```

- `readiness_probe {`: Starts the nested `readiness_probe` block: A health check; while it fails, Azure sends no traffic to the container.
- `transport               = "HTTP"`: `transport`: The protocol the probe uses (`HTTP`). Here: the text `"HTTP"`.
- `port                    = var.health_port`: `port`: The port the probe or rule applies to. Here: the input variable `health_port` (Port of the worker's health endpoint (/live and /ready); the platform's probes call it).
- `path                    = "/ready"`: `path`: The web path the probe requests. Here: the text `"/ready"`.
- `interval_seconds        = 15`: `interval_seconds`: Seconds between probe attempts. Here: the number `15`.
- `failure_count_threshold = 3`: `failure_count_threshold`: How many failed attempts in a row count as unhealthy. Here: the number `3`.
- `startup_probe {`: Starts the nested `startup_probe` block: A health check run during start-up; the other probes wait until it succeeds.
- `transport               = "HTTP"`: `transport`: The protocol the probe uses (`HTTP`). Here: the text `"HTTP"`.
- `port                    = var.health_port`: `port`: The port the probe or rule applies to. Here: the input variable `health_port` (Port of the worker's health endpoint (/live and /ready); the platform's probes call it).
- `path                    = "/live"`: `path`: The web path the probe requests. Here: the text `"/live"`.
- `interval_seconds        = 3`: `interval_seconds`: Seconds between probe attempts. Here: the number `3`.
- `failure_count_threshold = 10`: `failure_count_threshold`: How many failed attempts in a row count as unhealthy. Here: the number `10`.
- Closing lines: `}` end the blocks opened above.

**Line 85**

```hcl
  }
```

- Closing line: `}` ends the block opened above.

**Line 86**

```hcl
}
```

- Closing line: `}` ends the block opened above.

## Try it yourself

Run the module's tests (no ingress, no secret blocks, probes, refused connection strings).

```bash
cd infra/modules/worker_app && terraform init -backend=false -input=false >/dev/null && terraform test 2>&1 | tail -4
```

You should see something like this:

```text
tests/worker_app.tftest.hcl... tearing down
tests/worker_app.tftest.hcl... pass

Success! 9 passed, 0 failed.
```

Find the comment explaining the missing ingress.

```bash
grep -n 'ingress' infra/modules/worker_app/main.tf
```

You should see something like this:

```text
28:  # No ingress block: the worker is not reachable from outside. Only the platform's probes reach the health port.
```

## Mistakes people make

- Probes that call a dependency. If the dependency's role is removed, the app restarts in a loop; liveness here checks only the process.
- Putting secrets in environment variables.
- Forgetting that scale-to-zero adds a cold start to the first request.
- Storing data on the replica's own disk and expecting it to survive.
- Attaching two identities and not saying which one the code should use.

## Check yourself

1. **What is a replica?**
   Answer: One running copy of the app's container.

2. **What does a failing liveness probe cause?**
   Answer: The platform restarts the replica.

3. **What does `min_replicas = 0` mean?**
   Answer: The app scales to zero when idle.

4. **Where do the app's console logs go?**
   Answer: To the environment's Log Analytics workspace.

5. **How does the app prove who it is to Key Vault?**
   Answer: With a token from its attached managed identity.

## Further reading

- Container Apps overview: https://learn.microsoft.com/en-us/azure/container-apps/overview
- Health probes: https://learn.microsoft.com/en-us/azure/container-apps/health-probes
- Managed identity: https://learn.microsoft.com/en-us/azure/container-apps/managed-identity
