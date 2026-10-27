resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  suffix = coalesce(var.suffix, random_string.suffix.result)

  names = {
    resource_group  = "rg-${var.name_prefix}"
    workspace       = "law-${var.name_prefix}"
    worker_identity = "id-${var.name_prefix}-worker"
    pull_identity   = "id-${var.name_prefix}-pull"
    namespace       = "sb-${var.name_prefix}-${local.suffix}"
    registry        = "acr${var.name_prefix}${local.suffix}"
    environment     = "cae-${var.name_prefix}"
    worker          = "ca-${var.name_prefix}-worker"
    budget          = "budget-${var.name_prefix}"
  }

  tags = merge(
    {
      project     = "azure-service-bus-worker"
      environment = var.environment
      managed_by  = "terraform"
      owner       = "sumit-srivastava"
    },
    var.tags,
  )

  queue_ids = module.servicebus.queue_ids

  # The one place that decides who may do what. Every scope is one queue; nobody holds the namespace-wide owner role.
  worker_assignments = {
    for queue_name, queue_id in local.queue_ids : "worker_receives_${queue_name}" => {
      principal_id = module.worker_identity.principal_id
      role         = "Azure Service Bus Data Receiver"
      scope        = queue_id
    }
  }

  pull_assignments = {
    pull_reads_registry = {
      principal_id = module.pull_identity.principal_id
      role         = "AcrPull"
      scope        = module.registry.id
    }
  }

  operator_assignments = merge([
    for queue_name, queue_id in local.queue_ids : {
      "operator_sends_${queue_name}" = {
        principal_id   = var.operator_object_id
        principal_type = "User"
        role           = "Azure Service Bus Data Sender"
        scope          = queue_id
      }
      "operator_receives_${queue_name}" = {
        principal_id   = var.operator_object_id
        principal_type = "User"
        role           = "Azure Service Bus Data Receiver"
        scope          = queue_id
      }
    }
    if var.operator_object_id != null
  ]...)
}

resource "azurerm_resource_group" "this" {
  name     = local.names.resource_group
  location = var.location
  tags     = local.tags
}

module "log_analytics" {
  source = "../../modules/log_analytics"

  name                = local.names.workspace
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

module "worker_identity" {
  source = "../../modules/user_assigned_identity"

  name                = local.names.worker_identity
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

module "pull_identity" {
  source = "../../modules/user_assigned_identity"

  name                = local.names.pull_identity
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

module "servicebus" {
  source = "../../modules/servicebus"

  name                       = local.names.namespace
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = module.log_analytics.id
  alert_email_addresses      = var.alert_email_addresses
  tags                       = local.tags

  queues = {
    orders          = {}
    orders-sessions = { requires_session = true }
  }
}

module "registry" {
  source = "../../modules/container_registry"

  name                = local.names.registry
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  tags                = local.tags
}

module "role_assignments" {
  source = "../../modules/role_assignments"

  assignments = merge(local.worker_assignments, local.pull_assignments, local.operator_assignments)
}

module "worker_app" {
  source = "../../modules/worker_app"
  count  = var.deploy_worker ? 1 : 0

  name                       = local.names.worker
  environment_name           = local.names.environment
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = module.log_analytics.id
  image                      = coalesce(var.image, "unused.azurecr.io/unused:0")
  worker_identity_id         = module.worker_identity.id
  pull_identity_id           = module.pull_identity.id
  registry_server            = module.registry.login_server
  tags                       = local.tags

  # Addresses, names and tuning knobs. Nothing here is a secret, and there is no connection string to put here.
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

  # The identity must hold its role before the worker starts, or its first receive is a denial.
  depends_on = [module.role_assignments]
}

module "budget" {
  source = "../../modules/budget"
  count  = length(var.budget_contact_emails) > 0 ? 1 : 0

  name            = local.names.budget
  subscription_id = var.subscription_id
  amount          = var.budget_amount
  start_date      = coalesce(var.budget_start_date, "2026-01-01T00:00:00Z")
  contact_emails  = var.budget_contact_emails
}
