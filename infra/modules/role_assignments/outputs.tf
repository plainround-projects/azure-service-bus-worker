output "assignments" {
  description = "What was assigned, by key: principal, role and scope."
  value = {
    for key, assignment in azurerm_role_assignment.this : key => {
      principal_id = assignment.principal_id
      role         = assignment.role_definition_name
      scope        = assignment.scope
    }
  }
}
