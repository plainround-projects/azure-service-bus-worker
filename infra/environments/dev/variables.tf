variable "subscription_id" {
  description = "Subscription GUID (`az account show --query id`)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "tenant_id" {
  description = "Entra tenant GUID (`az account show --query tenantId`)."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.tenant_id))
    error_message = "tenant_id must be a GUID."
  }
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "westeurope"
}

variable "environment" {
  description = "Environment name, used in tags."
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Short lowercase word in every resource name. Letters and digits only."
  type        = string
  default     = "orders"

  validation {
    condition     = can(regex("^[a-z0-9]{3,12}$", var.name_prefix))
    error_message = "name_prefix must be 3 to 12 lowercase letters or digits."
  }
}

variable "suffix" {
  description = "Characters that make the namespace and registry names globally unique. Leave null to generate five."
  type        = string
  default     = null

  validation {
    condition     = var.suffix == null || can(regex("^[a-z0-9]{3,6}$", var.suffix))
    error_message = "suffix must be 3 to 6 lowercase letters or digits."
  }
}

variable "operator_object_id" {
  description = "Object id of the person who runs the lesson (`az ad signed-in-user show --query id`). They get Data Sender and Data Receiver on both queues, so the producer script, a local worker and the dead-letter replay tool work from a laptop. Null grants nothing."
  type        = string
  default     = null
}

variable "alert_email_addresses" {
  description = "Recipients of the dead-letter alert. Empty creates no alert."
  type        = list(string)
  default     = []
}

variable "deploy_worker" {
  description = "False creates everything except the container app, so the image can be built in the registry first. True adds the worker (set `image`)."
  type        = bool
  default     = false
}

variable "image" {
  description = "Worker image, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Required when deploy_worker is true."
  type        = string
  default     = null

  validation {
    condition     = !var.deploy_worker || var.image != null
    error_message = "Set image when deploy_worker is true."
  }
}

variable "worker_queue" {
  description = "The queue the deployed worker reads. orders-sessions needs worker_use_sessions = true."
  type        = string
  default     = "orders"

  validation {
    condition     = contains(["orders", "orders-sessions"], var.worker_queue)
    error_message = "worker_queue must be orders or orders-sessions."
  }
}

variable "worker_use_sessions" {
  description = "Whether the deployed worker uses session receivers (for orders-sessions)."
  type        = bool
  default     = false
}

variable "worker_mode" {
  description = "naive or idempotent (lesson step 3)."
  type        = string
  default     = "idempotent"

  validation {
    condition     = contains(["naive", "idempotent"], var.worker_mode)
    error_message = "worker_mode must be naive or idempotent."
  }
}

variable "worker_lock_renewal_seconds" {
  description = "Automatic lock renewal in seconds; 0 turns it off (lesson step 2)."
  type        = number
  default     = 300
}

variable "worker_slow_every" {
  description = "Chaos for lesson step 2: slow the first delivery of every Nth sequence number. 0 is off."
  type        = number
  default     = 0
}

variable "budget_contact_emails" {
  description = "Recipients of the budget alerts. An empty list creates no budget."
  type        = list(string)
  default     = []
}

variable "budget_amount" {
  description = "Monthly budget in the billing currency."
  type        = number
  default     = 30
}

variable "budget_start_date" {
  description = "First of a month at midnight UTC, for example 2026-11-01T00:00:00Z. Required when budget_contact_emails is set."
  type        = string
  default     = null

  validation {
    condition     = length(var.budget_contact_emails) == 0 || var.budget_start_date != null
    error_message = "Set budget_start_date when budget_contact_emails is set."
  }
}

variable "tags" {
  description = "Extra tags merged into the standard ones."
  type        = map(string)
  default     = {}
}
