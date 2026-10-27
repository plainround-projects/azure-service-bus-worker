resource "azurerm_role_assignment" "this" {
  for_each = var.assignments

  principal_id         = each.value.principal_id
  principal_type       = each.value.principal_type
  role_definition_name = each.value.role
  scope                = each.value.scope

  # A service principal created seconds ago may not have replicated yet; the principal type avoids the lookup.
  skip_service_principal_aad_check = each.value.principal_type == "ServicePrincipal"
}
