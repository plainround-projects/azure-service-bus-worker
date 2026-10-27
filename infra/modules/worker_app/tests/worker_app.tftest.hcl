mock_provider "azurerm" {}

variables {
  name                       = "ca-orders-worker"
  environment_name           = "cae-orders"
  resource_group_name        = "rg-test"
  location                   = "westeurope"
  log_analytics_workspace_id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.OperationalInsights/workspaces/law-test"
  image                      = "acrtest.azurecr.io/azure-service-bus-worker:0.1.0"
  worker_identity_id         = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-worker"
  pull_identity_id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-pull"
  registry_server            = "acrtest.azurecr.io"
  env = {
    AZURE_CLIENT_ID = "00000000-0000-0000-0000-000000000000"
    SB_NAMESPACE    = "sb-orders-abcde.servicebus.windows.net"
    SB_QUEUE        = "orders"
  }
}

run "carries_no_secret_blocks_and_only_the_given_plain_variables" {
  command = plan

  assert {
    condition     = length(azurerm_container_app.this.secret) == 0
    error_message = "the worker must hold no secret"
  }

  assert {
    condition     = toset([for variable in one(one(azurerm_container_app.this.template).container).env : variable.name]) == toset(["AZURE_CLIENT_ID", "SB_NAMESPACE", "SB_QUEUE"])
    error_message = "only the given variables may be set"
  }

  assert {
    condition     = alltrue([for variable in one(one(azurerm_container_app.this.template).container).env : variable.secret_name == null])
    error_message = "no variable may reference a secret"
  }
}

run "has_no_ingress_so_nothing_can_connect_to_the_worker" {
  command = plan

  assert {
    condition     = length(azurerm_container_app.this.ingress) == 0
    error_message = "the worker pulls from the queue; it must not be reachable"
  }
}

run "runs_as_both_identities_and_pulls_with_the_pull_identity" {
  command = plan

  assert {
    condition     = length(one(azurerm_container_app.this.identity).identity_ids) == 2
    error_message = "the worker and pull identities must both be attached"
  }

  assert {
    condition     = one(azurerm_container_app.this.registry).identity == var.pull_identity_id
    error_message = "the registry must be reached with the pull identity"
  }
}

run "probes_the_health_port_and_mounts_the_ledger_volume" {
  command = plan

  assert {
    condition     = one(one(one(azurerm_container_app.this.template).container).liveness_probe).path == "/live" && one(one(one(azurerm_container_app.this.template).container).readiness_probe).path == "/ready"
    error_message = "liveness and readiness must call /live and /ready"
  }

  assert {
    condition     = one(one(azurerm_container_app.this.template).volume).storage_type == "EmptyDir"
    error_message = "the ledger volume is ephemeral"
  }
}

run "refuses_a_variable_named_like_a_credential" {
  command = plan

  variables {
    env = {
      SB_CONNECTION_STRING = "x"
    }
  }

  expect_failures = [var.env]
}

run "refuses_a_shared_access_key_variable_by_name" {
  command = plan

  variables {
    env = {
      SERVICEBUS_SHARED_ACCESS = "x"
    }
  }

  expect_failures = [var.env]
}

run "refuses_a_variable_valued_like_a_service_bus_connection_string" {
  command = plan

  variables {
    env = {
      BUS = "Endpoint=sb://mybus.servicebus.windows.net/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=abc"
    }
  }

  expect_failures = [var.env]
}

run "refuses_the_latest_tag" {
  command = plan

  variables {
    image = "acrtest.azurecr.io/azure-service-bus-worker:latest"
  }

  expect_failures = [var.image]
}

run "refuses_zero_replicas" {
  command = plan

  variables {
    replicas = 0
  }

  expect_failures = [var.replicas]
}
