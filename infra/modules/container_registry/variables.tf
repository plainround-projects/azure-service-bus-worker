variable "name" {
  description = "Registry name: 5 to 50 letters and digits, globally unique."
  type        = string

  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.name))
    error_message = "A registry name has 5 to 50 letters and digits."
  }
}

variable "resource_group_name" {
  description = "Resource group that holds the registry."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "sku" {
  description = "Basic is the cheapest tier and enough to build and pull one image."
  type        = string
  default     = "Basic"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku)
    error_message = "sku must be Basic, Standard or Premium."
  }
}

variable "tags" {
  description = "Tags applied to the registry."
  type        = map(string)
  default     = {}
}
