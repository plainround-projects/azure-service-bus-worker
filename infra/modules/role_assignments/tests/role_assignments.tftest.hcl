mock_provider "azurerm" {}

variables {
  assignments = {
    blob = {
      principal_id = "22222222-2222-2222-2222-222222222222"
      role         = "Azure Service Bus Data Receiver"
      scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde/queues/orders"
    }
  }
}

run "accepts_a_queue_scope_and_assigns_without_the_directory_lookup" {
  command = plan

  assert {
    condition     = azurerm_role_assignment.this["blob"].skip_service_principal_aad_check
    error_message = "a new service principal must be assigned by its type"
  }

  assert {
    condition     = azurerm_role_assignment.this["blob"].role_definition_name == "Azure Service Bus Data Receiver"
    error_message = "the role must be the one requested"
  }
}

run "refuses_a_resource_group_scope" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Azure Service Bus Data Receiver"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test"
      }
    }
  }

  expect_failures = [var.assignments]
}

run "refuses_a_subscription_scope" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Reader"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000"
      }
    }
  }

  expect_failures = [var.assignments]
}

run "refuses_the_namespace_wide_owner_role" {
  command = plan

  variables {
    assignments = {
      owner = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Azure Service Bus Data Owner"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.ServiceBus/namespaces/sb-orders-abcde"
      }
    }
  }

  expect_failures = [var.assignments]
}

run "refuses_a_management_role" {
  command = plan

  variables {
    assignments = {
      owner = {
        principal_id = "22222222-2222-2222-2222-222222222222"
        role         = "Contributor"
        scope        = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"
      }
    }
  }

  expect_failures = [var.assignments]
}

run "refuses_an_unknown_principal_type" {
  command = plan

  variables {
    assignments = {
      blob = {
        principal_id   = "22222222-2222-2222-2222-222222222222"
        role           = "Reader"
        scope          = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-test/providers/Microsoft.KeyVault/vaults/kv-test"
        principal_type = "Robot"
      }
    }
  }

  expect_failures = [var.assignments]
}
