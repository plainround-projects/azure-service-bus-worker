output "id" {
  description = "Namespace resource id."
  value       = azurerm_servicebus_namespace.this.id
}

output "name" {
  description = "Namespace name."
  value       = azurerm_servicebus_namespace.this.name
}

output "fully_qualified_namespace" {
  description = "Host name the SDK connects to, for example mybus.servicebus.windows.net: the programs' SB_NAMESPACE."
  value       = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
}

output "queue_ids" {
  description = "Queue resource ids by name: the narrowest scope for the Data Sender and Data Receiver roles."
  value       = { for name, queue in azurerm_servicebus_queue.this : name => queue.id }
}

output "queue_names" {
  description = "Queue names."
  value       = keys(azurerm_servicebus_queue.this)
}
