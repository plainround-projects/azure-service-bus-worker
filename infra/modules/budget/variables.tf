variable "name" {
  description = "Budget name."
  type        = string
}

variable "subscription_id" {
  description = "Subscription GUID the budget watches."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$", var.subscription_id))
    error_message = "subscription_id must be a GUID."
  }
}

variable "amount" {
  description = "Monthly amount in the billing currency."
  type        = number

  validation {
    condition     = var.amount > 0
    error_message = "amount must be positive."
  }
}

variable "start_date" {
  description = "First day of the budget's first month, as 2026-11-01T00:00:00Z. Azure requires the first of a month."
  type        = string

  validation {
    condition     = can(regex("^[0-9]{4}-[0-9]{2}-01T00:00:00Z$", var.start_date))
    error_message = "start_date must be the first of a month at midnight UTC, for example 2026-11-01T00:00:00Z."
  }
}

variable "contact_emails" {
  description = "Addresses that receive the alerts."
  type        = list(string)

  validation {
    condition     = length(var.contact_emails) > 0
    error_message = "At least one contact email is needed or the budget alerts nobody."
  }
}

variable "thresholds_percent" {
  description = "Actual-spend percentages that send an alert."
  type        = list(number)
  default     = [80, 100]
}
