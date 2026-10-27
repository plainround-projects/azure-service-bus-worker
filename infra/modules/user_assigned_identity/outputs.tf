output "id" {
  description = "Resource id; a container app lists it under `identity_ids`."
  value       = azurerm_user_assigned_identity.this.id
}

output "principal_id" {
  description = "Object id of the identity's service principal; role assignments take this, not the client id."
  value       = azurerm_user_assigned_identity.this.principal_id
}

output "client_id" {
  description = "Application id; the app's AZURE_CLIENT_ID. It names the identity and is not a secret."
  value       = azurerm_user_assigned_identity.this.client_id
}

output "name" {
  description = "Identity name."
  value       = azurerm_user_assigned_identity.this.name
}
