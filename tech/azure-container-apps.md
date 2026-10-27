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
