output "name" {
  description = "Container app name; `az containerapp exec` and `az containerapp logs show` take it."
  value       = azurerm_container_app.this.name
}

output "environment_id" {
  description = "Container Apps environment id."
  value       = azurerm_container_app_environment.this.id
}
