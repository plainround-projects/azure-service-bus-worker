# Plans and applies the whole environment against a mocked azurerm provider: no credentials, no network.
# It proves the composition (who holds which role on which queue, what the worker is told) and the guards, not Azure's behavior.

mock_provider "azurerm" {
  mock_resource "azurerm_servicebus_namespace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"
    }
  }
  mock_resource "azurerm_servicebus_queue" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/mock"
    }
  }
  mock_resource "azurerm_container_registry" {
    defaults = {
      id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ContainerRegistry/registries/acrordersabcde"
      login_server = "acrordersabcde.azurecr.io"
    }
  }
  mock_resource "azurerm_log_analytics_workspace" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.OperationalInsights/workspaces/law-orders"
    }
  }
  mock_resource "azurerm_container_app_environment" {
    defaults = {
      id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.App/managedEnvironments/cae-orders"
    }
  }
}

override_resource {
  target = module.servicebus.azurerm_servicebus_queue.this["orders"]
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"
  }
}

override_resource {
  target = module.servicebus.azurerm_servicebus_queue.this["orders-sessions"]
  values = {
    id = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions"
  }
}

override_resource {
  target = module.worker_identity.azurerm_user_assigned_identity.this
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-worker"
    principal_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    client_id    = "cccccccc-cccc-cccc-cccc-cccccccccccc"
  }
}

override_resource {
  target = module.pull_identity.azurerm_user_assigned_identity.this
  values = {
    id           = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ManagedIdentity/userAssignedIdentities/id-orders-pull"
    principal_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    client_id    = "dddddddd-dddd-dddd-dddd-dddddddddddd"
  }
}

variables {
  subscription_id = "00000000-0000-0000-0000-000000000000"
  tenant_id       = "11111111-1111-1111-1111-111111111111"
  suffix          = "abcde"
}

run "the_worker_holds_only_data_receiver_one_per_queue_and_never_the_owner_role" {
  command = apply

  assert {
    condition     = length(output.worker_role_assignments) == 2
    error_message = "one Data Receiver assignment per queue and nothing else"
  }

  assert {
    condition     = alltrue([for assignment in output.worker_role_assignments : assignment.role == "Azure Service Bus Data Receiver"])
    error_message = "the worker may only receive"
  }

  assert {
    condition = toset([for assignment in output.worker_role_assignments : assignment.scope]) == toset([
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders",
      "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-orders/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders-sessions",
    ])
    error_message = "each assignment must be scoped to one queue, not the namespace or the group"
  }
}

run "the_pull_identity_reads_the_registry_and_nothing_else" {
  command = apply

  assert {
    condition     = length([for assignment in module.role_assignments.assignments : assignment if assignment.principal_id == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"]) == 1
    error_message = "the pull identity holds one role"
  }
}

run "no_operator_roles_unless_asked" {
  command = apply

  assert {
    condition     = length(output.operator_role_assignments) == 0 && length(module.role_assignments.assignments) == 3
    error_message = "two for the worker, one for the pull identity, none for an operator that was not named"
  }
}

run "a_named_operator_may_send_and_receive_on_each_queue_but_not_manage_the_namespace" {
  command = apply

  variables {
    operator_object_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
  }

  assert {
    condition     = length(output.operator_role_assignments) == 4
    error_message = "Data Sender and Data Receiver on each of the two queues"
  }

  assert {
    condition     = toset([for assignment in output.operator_role_assignments : assignment.role]) == toset(["Azure Service Bus Data Sender", "Azure Service Bus Data Receiver"])
    error_message = "the operator holds the two data roles and no management role"
  }
}

run "the_first_phase_builds_everything_except_the_worker" {
  command = apply

  assert {
    condition     = output.worker_app_name == null
    error_message = "with deploy_worker false there is no container app"
  }

  assert {
    condition     = output.servicebus_namespace == "sb-orders-abcde.servicebus.windows.net" && toset(output.queue_names) == toset(["orders", "orders-sessions"])
    error_message = "the namespace host and both queues must be exposed to the programs"
  }
}

run "the_second_phase_adds_the_worker" {
  command = apply

  variables {
    deploy_worker = true
    image         = "acrordersabcde.azurecr.io/azure-service-bus-worker:0.1.0"
  }

  assert {
    condition     = output.worker_app_name == "ca-orders-worker"
    error_message = "the worker must be created in phase two"
  }
}

run "a_worker_without_an_image_is_refused" {
  command = plan

  variables {
    deploy_worker = true
  }

  expect_failures = [var.image]
}

run "an_unknown_worker_queue_is_refused" {
  command = plan

  variables {
    worker_queue = "payments"
  }

  expect_failures = [var.worker_queue]
}

run "a_budget_needs_a_start_date" {
  command = plan

  variables {
    budget_contact_emails = ["owner@example.com"]
  }

  expect_failures = [var.budget_start_date]
}

run "names_are_built_from_the_prefix_and_suffix_and_tagged" {
  command = plan

  assert {
    condition     = azurerm_resource_group.this.name == "rg-orders" && module.servicebus.name == "sb-orders-abcde" && module.registry.name == "acrordersabcde"
    error_message = "names must follow rg-orders, sb-orders-<suffix>, acrorders<suffix>"
  }

  assert {
    condition     = azurerm_resource_group.this.tags["managed_by"] == "terraform" && azurerm_resource_group.this.tags["project"] == "azure-service-bus-worker"
    error_message = "the standard tags must be present"
  }
}
