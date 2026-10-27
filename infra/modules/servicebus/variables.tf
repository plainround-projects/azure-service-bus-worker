variable "name" {
  description = "Namespace name: 6 to 50 letters, digits and hyphens, globally unique, starting with a letter."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]$", var.name))
    error_message = "A namespace name has 6 to 50 characters, starts with a letter, ends with a letter or digit and holds letters, digits and hyphens."
  }
}

variable "resource_group_name" {
  description = "Resource group that holds the namespace."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "queues" {
  description = <<-EOT
    Queues by name. Defaults follow the lesson: a 30-second lock, ten deliveries before the dead-letter queue.
    `requires_session` cannot be changed on an existing queue, which is why the session queue is a second queue.
  EOT
  type = map(object({
    lock_duration       = optional(string, "PT30S")
    max_delivery_count  = optional(number, 10)
    requires_session    = optional(bool, false)
    default_message_ttl = optional(string, "P1D")
  }))

  validation {
    condition     = alltrue([for queue in var.queues : queue.lock_duration != null && can(regex("^PT([0-9]+M)?([0-9]+S)?$", queue.lock_duration))])
    error_message = "lock_duration must be an ISO 8601 duration of at most 5 minutes, such as PT30S."
  }

  validation {
    condition     = alltrue([for queue in var.queues : queue.max_delivery_count >= 1 && queue.max_delivery_count <= 2000])
    error_message = "max_delivery_count must be between 1 and 2000."
  }
}

variable "log_analytics_workspace_id" {
  description = "Workspace that receives the operational logs and metrics."
  type        = string
}

variable "alert_email_addresses" {
  description = "Recipients of the dead-letter alert. Empty creates no alert."
  type        = list(string)
  default     = []
}

variable "tags" {
  description = "Tags applied to the namespace and the alert."
  type        = map(string)
  default     = {}
}
