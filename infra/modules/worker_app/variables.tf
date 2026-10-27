variable "name" {
  description = "Container app name, for example ca-orders-worker."
  type        = string
}

variable "environment_name" {
  description = "Container Apps environment name."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds both."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Workspace that receives the console logs."
  type        = string
}

variable "image" {
  description = "Image to run, for example myregistry.azurecr.io/azure-service-bus-worker:0.1.0. Use a version tag or a digest, never latest."
  type        = string

  validation {
    condition     = !endswith(var.image, ":latest") && can(regex(":[^/]+$|@sha256:[0-9a-f]{64}$", var.image))
    error_message = "image must carry a version tag or a digest, and not be :latest."
  }
}

variable "health_port" {
  description = "Port of the worker's health endpoint (/live and /ready); the platform's probes call it."
  type        = number
  default     = 8080
}

variable "ledger_directory" {
  description = "Directory where the ephemeral volume is mounted; the worker's LEDGER_PATH points into it."
  type        = string
  default     = "/data"
}

variable "worker_identity_id" {
  description = "Resource id of the identity the worker runs as (it holds the Data Receiver role on its queue)."
  type        = string
}

variable "pull_identity_id" {
  description = "Resource id of the identity that only pulls the image (AcrPull on the registry)."
  type        = string
}

variable "registry_server" {
  description = "Registry host, for example myregistry.azurecr.io."
  type        = string
}

variable "env" {
  description = "Plain environment variables: addresses and the client id of the identity. Credentials are refused by name and by value."
  type        = map(string)
  default     = {}

  validation {
    condition = !anytrue([
      for name in keys(var.env) :
      can(regex("(?i)(password|passwd|connection_?string|client_?secret|account_?key|sas_?token|api_?key|shared_?access)", name))
    ])
    error_message = "An environment variable name suggests a credential (password, connection string, client secret, account key, SAS token, API key). The app authenticates with its managed identity instead."
  }

  validation {
    condition = !anytrue([
      for value in values(var.env) :
      can(regex("(?i)(accountkey=|sharedaccesskey=|sharedaccesssignature=|[?&]sig=|password=|pwd=|-----BEGIN|endpoint=sb://)", value))
    ])
    error_message = "An environment variable value looks like a connection string, SAS token or private key."
  }
}

variable "replicas" {
  description = "Number of replicas. Keep 1: each replica has its own SQLite ledger, so the cross-instance checks of the lesson run locally (make workers)."
  type        = number
  default     = 1

  validation {
    condition     = var.replicas >= 1 && var.replicas <= 10
    error_message = "replicas must be between 1 and 10."
  }
}

variable "cpu" {
  description = "vCPU per replica."
  type        = number
  default     = 0.25
}

variable "memory" {
  description = "Memory per replica; Container Apps pairs 0.25 vCPU with 0.5Gi."
  type        = string
  default     = "0.5Gi"
}

variable "tags" {
  description = "Tags applied to both resources."
  type        = map(string)
  default     = {}
}
