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

variable "environment" {
  description = "Environment name used in resource tags"
  type        = string
  default     = "poc"
}

variable "project" {
  description = "Project name for tagging"
  type        = string
  default     = "genai-llm-aks"
}

variable "owner" {
  description = "Owner name for tagging"
  type        = string
  default     = "sarath-babu"
}

variable "azure_openai_api_key" {
  description = "Azure OpenAI API key for GPT-4o fallback"
  type        = string
  sensitive   = true
  default     = ""
}

variable "dockerhub_token" {
  description = "DockerHub access token for image pulls"
  type        = string
  sensitive   = true
  default     = ""
}

variable "vm_size" {
  description = "VM size for AKS node pools"
  type        = string
  default     = "Standard_D2s_v7"
}
