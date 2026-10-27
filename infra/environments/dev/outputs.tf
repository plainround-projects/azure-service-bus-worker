output "resource_group_name" {
  description = "The one resource group; destroying the environment removes it."
  value       = azurerm_resource_group.this.name
}

output "namespace_name" {
  description = "Service Bus namespace name."
  value       = module.servicebus.name
}

output "servicebus_namespace" {
  description = "The programs' SB_NAMESPACE (fully qualified host name)."
  value       = module.servicebus.fully_qualified_namespace
}

output "queue_names" {
  description = "The queues: orders and orders-sessions."
  value       = module.servicebus.queue_names
}

output "registry_name" {
  description = "Registry name for `az acr build`."
  value       = module.registry.name
}

output "registry_login_server" {
  description = "Registry host, the prefix of the image name."
  value       = module.registry.login_server
}

output "worker_identity_name" {
  description = "Name of the identity the worker runs as."
  value       = module.worker_identity.name
}

output "worker_identity_client_id" {
  description = "The worker's AZURE_CLIENT_ID. It names the identity and is not a secret."
  value       = module.worker_identity.client_id
}

output "worker_identity_principal_id" {
  description = "Object id of the worker identity; denial messages in the logs show this value."
  value       = module.worker_identity.principal_id
}

output "log_analytics_customer_id" {
  description = "Workspace customer id for `az monitor log-analytics query --workspace`."
  value       = module.log_analytics.workspace_id
}

output "worker_app_name" {
  description = "Container app name, or null until deploy_worker is true."
  value       = one(module.worker_app[*].name)
}

output "worker_role_assignments" {
  description = "The worker identity's role assignments: Data Receiver, one per queue, nothing else."
  value = [
    for assignment in module.role_assignments.assignments :
    { role = assignment.role, scope = assignment.scope }
    if assignment.principal_id == module.worker_identity.principal_id
  ]
}

output "operator_role_assignments" {
  description = "The operator's role assignments (empty when operator_object_id is null)."
  value = [
    for key, assignment in module.role_assignments.assignments :
    { key = key, role = assignment.role, scope = assignment.scope }
    if startswith(key, "operator_")
  ]
}
