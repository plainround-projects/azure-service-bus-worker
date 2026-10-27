variable "assignments" {
  description = <<-EOT
    Role assignments by a stable key. Each entry names the principal's object id (not its client id), the built-in
    role and the scope. The scope must be a single resource or sub-resource: a subscription or a resource group is
    refused, which is the "narrowest scope that works" rule written as code.
  EOT
  type = map(object({
    principal_id   = string
    role           = string
    scope          = string
    principal_type = optional(string, "ServicePrincipal")
  }))

  validation {
    condition = alltrue([
      for assignment in var.assignments :
      can(regex("^/subscriptions/[^/]+/resourceGroups/[^/]+/providers/.+/.+", assignment.scope))
    ])
    error_message = "Every scope must be a resource (/subscriptions/.../resourceGroups/.../providers/...), never a subscription or a resource group."
  }

  validation {
    condition = alltrue([
      for assignment in var.assignments :
      contains(["ServicePrincipal", "User", "Group"], assignment.principal_type)
    ])
    error_message = "principal_type must be ServicePrincipal, User or Group."
  }

  validation {
    condition     = !anytrue([for assignment in var.assignments : contains(["Owner", "Contributor", "User Access Administrator", "Azure Service Bus Data Owner"], assignment.role)])
    error_message = "Owner, Contributor, User Access Administrator and Azure Service Bus Data Owner are too wide; this project assigns the Data Sender and Data Receiver roles on single queues."
  }
}
