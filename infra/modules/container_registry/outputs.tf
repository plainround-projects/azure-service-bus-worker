output "id" {
  description = "Resource id; the scope for AcrPull."
  value       = azurerm_container_registry.this.id
}

output "name" {
  description = "Registry name; `az acr build --registry` takes it."
  value       = azurerm_container_registry.this.name
}

output "login_server" {
  description = "Registry host, for example myregistry.azurecr.io."
  value       = azurerm_container_registry.this.login_server
}
