# =============================================================================
# Terraform: GenAI AKS Cluster with Autoscaling
# Author: Sarath Babu | Senior DevOps + AI/MLOps Architect
# Azure Subscription: 7908ea24-a708-4291-be15-98426e3e9ca5
# GitHub: https://github.com/esarath/genai-aks-poc
# =============================================================================

terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.95"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  backend "azurerm" {
    resource_group_name  = "rg-genai-tfstate"
    storage_account_name = "stgenaitfstate"
    container_name       = "tfstate"
    key                  = "genai-aks-poc.terraform.tfstate"
  }
}

provider "azurerm" {
  subscription_id = "7908ea24-a708-4291-be15-98426e3e9ca5"
  features {
    resource_group {
      prevent_deletion_if_contains_resources = false
    }
    key_vault {
      purge_soft_delete_on_destroy    = true
      recover_soft_deleted_key_vaults = true
    }
  }
}

# =============================================================================
# DATA SOURCES
# =============================================================================
data "azurerm_subscription" "current" {}

data "azurerm_client_config" "current" {}

# =============================================================================
# RESOURCE GROUP
# =============================================================================
resource "azurerm_resource_group" "genai" {
  name     = var.resource_group_name
  location = var.location

  tags = local.common_tags
}

# =============================================================================
# VIRTUAL NETWORK
# =============================================================================
resource "azurerm_virtual_network" "genai" {
  name                = "vnet-genai-poc"
  location            = azurerm_resource_group.genai.location
  resource_group_name = azurerm_resource_group.genai.name
  address_space       = ["10.0.0.0/16"]

  tags = local.common_tags
}

resource "azurerm_subnet" "aks_nodes" {
  name                 = "snet-aks-nodes"
  resource_group_name  = azurerm_resource_group.genai.name
  virtual_network_name = azurerm_virtual_network.genai.name
  address_prefixes     = ["10.0.1.0/24"]
}

resource "azurerm_subnet" "aks_pods" {
  name                 = "snet-aks-pods"
  resource_group_name  = azurerm_resource_group.genai.name
  virtual_network_name = azurerm_virtual_network.genai.name
  address_prefixes     = ["10.0.2.0/23"]
}

# =============================================================================
# LOG ANALYTICS WORKSPACE (Free Tier: 5GB/day)
# =============================================================================
resource "azurerm_log_analytics_workspace" "genai" {
  name                = "law-genai-poc"
  location            = azurerm_resource_group.genai.location
  resource_group_name = azurerm_resource_group.genai.name
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = local.common_tags
}

# =============================================================================
# AKS CLUSTER
# =============================================================================
resource "azurerm_kubernetes_cluster" "genai" {
  name                = var.cluster_name
  location            = azurerm_resource_group.genai.location
  resource_group_name = azurerm_resource_group.genai.name
  dns_prefix          = "genai-aks-poc"
  kubernetes_version  = var.kubernetes_version
  sku_tier            = "Free"  # Free tier

  # System Node Pool (Required)
  default_node_pool {
    name                        = "systempool"
    vm_size                     = "Standard_D2s_v7"
    node_count                  = 1
    min_count                   = 1
    max_count                   = 2
    enable_auto_scaling         = true
    enable_node_public_ip       = false
    os_disk_size_gb             = 50
    os_disk_type                = "Managed"
    type                        = "VirtualMachineScaleSets"
    vnet_subnet_id              = azurerm_subnet.aks_nodes.id
    only_critical_addons_enabled = true  # Taint: CriticalAddonsOnly

    node_labels = {
      "nodepool-type" = "system"
      "workload"      = "system"
    }

    upgrade_settings {
      max_surge = "10%"
    }
  }

  # Identity
  identity {
    type = "SystemAssigned"
  }

  # Network Profile
  network_profile {
    network_plugin     = "azure"
    network_policy     = "azure"
    load_balancer_sku  = "standard"
    service_cidr       = "10.1.0.0/16"
    dns_service_ip     = "10.1.0.10"
    outbound_type      = "loadBalancer"
  }

  # OMS Agent (Azure Monitor)
  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.genai.id
  }

  # Azure AD + RBAC

  # Workload Identity
  workload_identity_enabled         = true
  oidc_issuer_enabled               = true

  # Key Vault Secrets Provider
  key_vault_secrets_provider {
    secret_rotation_enabled  = true
    secret_rotation_interval = "2m"
  }

  # Auto-upgrade
  automatic_channel_upgrade = "patch"
  maintenance_window {
    allowed {
      day   = "Sunday"
      hours = [2, 4]
    }
  }

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      default_node_pool[0].node_count,
      kubernetes_version,
    ]
  }
}

# =============================================================================
# AI WORKLOAD NODE POOL (Autoscaling)
# =============================================================================
resource "azurerm_kubernetes_cluster_node_pool" "ai_workload" {
  name                  = "aiworkload"
  kubernetes_cluster_id = azurerm_kubernetes_cluster.genai.id
  vm_size               = "Standard_D2s_v7"
  min_count             = 1
  max_count             = 3
  enable_auto_scaling   = true
  os_disk_size_gb       = 50
  mode                  = "User"
  vnet_subnet_id        = azurerm_subnet.aks_nodes.id

  node_labels = {
    "nodepool-type" = "user"
    "workload"      = "ai-mlops"
    "app"           = "genai"
  }

  node_taints = [
    "workload=ai:NoSchedule"
  ]

  upgrade_settings {
    max_surge = "1"
  }

  tags = local.common_tags
}

# =============================================================================
# ROLE ASSIGNMENTS
# =============================================================================
# AKS → VNet
resource "azurerm_role_assignment" "aks_vnet" {
  scope                = azurerm_virtual_network.genai.id
  role_definition_name = "Network Contributor"
  principal_id         = azurerm_kubernetes_cluster.genai.identity[0].principal_id
}

# AKS → ACR (if using ACR instead of DockerHub)
resource "azurerm_container_registry" "genai" {
  name                = "acrgenaipoc${random_string.suffix.result}"
  resource_group_name = azurerm_resource_group.genai.name
  location            = azurerm_resource_group.genai.location
  sku                 = "Basic"
  admin_enabled       = false

  tags = local.common_tags
}

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                = azurerm_container_registry.genai.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.genai.kubelet_identity[0].object_id
}

# =============================================================================
# KEY VAULT FOR SECRETS
# =============================================================================
resource "azurerm_key_vault" "genai" {
  name                        = "kv-genai-poc-${random_string.suffix.result}"
  location                    = azurerm_resource_group.genai.location
  resource_group_name         = azurerm_resource_group.genai.name
  enabled_for_disk_encryption = true
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  soft_delete_retention_days  = 7
  purge_protection_enabled    = false
  sku_name                    = "standard"

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    key_permissions    = ["Get", "List", "Create", "Delete"]
    secret_permissions = ["Get", "List", "Set", "Delete", "Recover"]
  }

  tags = local.common_tags
}

# Secrets
resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "azure-openai-api-key"
  value        = var.azure_openai_api_key
  key_vault_id = azurerm_key_vault.genai.id
}

resource "azurerm_key_vault_secret" "dockerhub_token" {
  name         = "dockerhub-access-token"
  value        = var.dockerhub_token
  key_vault_id = azurerm_key_vault.genai.id
}

# =============================================================================
# LOCALS
# =============================================================================
locals {
  common_tags = {
    Project     = "GenAI-LLM-POC"
    Owner       = "Sarath-Babu"
    Environment = var.environment
    ManagedBy   = "Terraform"
    GitHub      = "https://github.com/esarath/genai-aks-poc"
  }
}
