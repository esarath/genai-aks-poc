variable "resource_group_name" {
  description = "Name of the Azure resource group"
  type        = string
  default     = "rg-genai-poc"
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "cluster_name" {
  description = "AKS cluster name"
  type        = string
  default     = "aks-genai-poc"
}

variable "kubernetes_version" {
  description = "Kubernetes version"
  type        = string
  default     = "1.34"
}

variable "qdrant_api_key" {
  description = "Qdrant API key (sensitive)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "azure_openai_key" {
  description = "Azure OpenAI API key (fallback LLM)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default = {
    environment = "poc"
    project     = "genai-llm-aks"
    owner       = "sarath-babu"
    managed-by  = "terraform"
  }
}
