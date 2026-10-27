resource "azurerm_container_app_environment" "this" {
  name                       = var.environment_name
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
  tags                       = var.tags
}

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
}
