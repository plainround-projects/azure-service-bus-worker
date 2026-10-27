output "id" {
  description = "Resource id of the workspace; diagnostic settings and the container app environment take this."
  value       = azurerm_log_analytics_workspace.this.id
}

output "name" {
  description = "Workspace name."
  value       = azurerm_log_analytics_workspace.this.name
}

output "workspace_id" {
  description = "The workspace's customer id (a GUID, not a secret); `az monitor log-analytics query --workspace` takes it."
  value       = azurerm_log_analytics_workspace.this.workspace_id
}
