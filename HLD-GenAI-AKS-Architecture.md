# High-Level Design: GenAI/LLM Pipeline on Azure AKS
**Project**: GenAI/LLM POC → Production on AKS (Free Tier)  
**Author**: Sarath Babu | Senior DevOps + AI/MLOps Architect  
**Azure Subscription**: 7908ea24-a708-4291-be15-98426e3e9ca5  
**GitHub**: https://github.com/esarath/  
**DockerHub**: esarathmails  
**Last Updated**: June 2026

---

## 1. Executive Summary

This document defines the High-Level Design for deploying a production-grade GenAI/LLM pipeline on Azure Kubernetes Service (AKS) using a free Azure subscription. The solution integrates Retrieval-Augmented Generation (RAG), vector databases, Model Context Protocol (MCP), and agentic AI workflows within a fully GitOps-driven, observable, and secure infrastructure.

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        DEVELOPER / DATA SCIENTIST                          │
│                         (Code → GitHub → Actions)                          │
└──────────────────────────────┬─────────────────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   GitHub Actions CI  │
                    │  (Build→Test→Push)   │
                    └──────────┬──────────┘
                               │ Docker Image
                    ┌──────────▼──────────┐
                    │     DockerHub        │
                    │   esarathmails/*    │
                    └──────────┬──────────┘
                               │ Image Pull
                    ┌──────────▼──────────┐
                    │       ArgoCD         │  ◄── GitHub GitOps Repo
                    │  (GitOps Operator)   │      (manifests/helm)
                    └──────────┬──────────┘
                               │ Deploy
┌──────────────────────────────▼─────────────────────────────────────────────┐
│                         AZURE AKS CLUSTER                                   │
│  Sub: 7908ea24-a708-4291-be15-98426e3e9ca5 | Region: East US               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    SYSTEM NODE POOL                                   │   │
│  │   (Standard_B2s | 1-3 nodes | System workloads, ArgoCD, Vault)     │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                     USER NODE POOL (Autoscaling)                     │   │
│  │   (Standard_B2s | 1-5 nodes | AI/LLM workloads, RAG, Vector DB)   │   │
│  │                                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │ RAG API  │  │Embedding │  │Vector DB │  │  LLM Gateway     │   │   │
│  │  │(FastAPI) │  │Service   │  │(Qdrant)  │  │(LiteLLM/Ollama)  │   │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  │                                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────────┐   │   │
│  │  │MCP Server│  │ LangChain│  │ Agent    │  │  Streamlit UI    │   │   │
│  │  │(Claude)  │  │ Orchestr.│  │Executor  │  │  (Demo App)      │   │   │
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    OBSERVABILITY STACK                                │   │
│  │     Prometheus ── Grafana ── Azure Monitor ── Log Analytics         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Component Interaction Map

| Component | Role | Technology | Integration |
|-----------|------|-----------|-------------|
| GitHub Actions | CI Pipeline | YAML Workflows | Triggers on push/PR |
| DockerHub | Image Registry | esarathmails/* | Pulled by AKS/ArgoCD |
| ArgoCD | GitOps Operator | Helm + Kustomize | Watches GitHub repo |
| AKS | Compute | K8s 1.29+ | Host for all workloads |
| Terraform | IaC | HCL | Provisions AKS, VNET, ACR |
| Qdrant | Vector DB | REST API | Stores embeddings |
| LangChain | RAG Orchestration | Python | Chains LLM + Vector DB |
| Ollama / LiteLLM | LLM Runtime | REST | Serves Phi-3/Mistral |
| MCP Server | Tool Protocol | Python SDK | Connects Claude to AKS |
| Prometheus | Metrics | PromQL | Scrapes all services |
| Grafana | Dashboards | JSON | LLM latency, throughput |
| Azure Monitor | Cloud Metrics | KQL | AKS node/pod metrics |
| HashiCorp Vault | Secrets | K8s Auth | API keys, tokens |

---

## 4. RAG + Vector DB + MCP Data Flow

```
User Query
    │
    ▼
[MCP Client / Claude API]
    │
    ▼
[MCP Server (K8s Pod)]
    │  tool_call: rag_query
    ▼
[RAG API - FastAPI]
    │
    ├──► [Embedding Service]
    │        │ text → vector (sentence-transformers)
    │        ▼
    │    [Qdrant Vector DB]
    │        │ similarity search (top-k)
    │        ▼
    │    [Retrieved Chunks]
    │
    ├──► [Prompt Builder]
    │        │ context + query → prompt
    │        ▼
    │    [LLM Gateway (LiteLLM)]
    │        │ routes to Ollama/Azure OpenAI
    │        ▼
    │    [Generated Response]
    │
    ▼
[Response → MCP → User]
    │
    ▼
[Metrics pushed to Prometheus]
(latency, token count, retrieval score)
```

---

## 5. CI/CD Pipeline Flow

```
Developer Push
     │
     ▼
GitHub (esarath/genai-aks-poc)
     │
     ├── Trigger: GitHub Actions Workflow
     │       ├── Lint + Unit Tests
     │       ├── docker build -t esarathmails/rag-api:$SHA
     │       ├── docker push esarathmails/rag-api:$SHA
     │       └── Update Helm values (image.tag: $SHA)
     │
     ▼
GitOps Repo (esarath/genai-aks-gitops)
     │
     ▼
ArgoCD (running in AKS)
     │  Detects manifest drift
     ▼
AKS Deployment
     │
     ├── Rolling update (maxSurge: 1, maxUnavailable: 0)
     ├── Health check via readiness probe
     └── Sync status → Slack / GitHub Status Check
```

---

## 6. End-to-End GenAI Solution Design

### 6.1 LLM Stack
- **Primary**: Ollama (Phi-3 Mini / Mistral 7B) — runs in AKS free tier
- **Fallback**: Azure OpenAI (gpt-4o-mini) via LiteLLM gateway
- **Routing**: LiteLLM handles model routing, rate limiting, cost tracking

### 6.2 Agentic Workflows
```
LangChain Agent
    ├── Tool: rag_search (Qdrant)
    ├── Tool: web_search (SerpAPI/Tavily)
    ├── Tool: code_exec (Python REPL)
    ├── Tool: k8s_query (MCP Server → kubectl)
    └── Tool: file_reader (Azure Blob Storage)
```

### 6.3 RAG Pipeline Variants
- **Naive RAG**: Direct embed → retrieve → generate
- **Advanced RAG**: Query rewriting + HyDE + re-ranking
- **Agentic RAG**: Agent decides when to retrieve, validates results

### 6.4 Embeddings Pipeline
- Model: `sentence-transformers/all-MiniLM-L6-v2` (free, runs in AKS)
- Chunking: 512 tokens, 50-token overlap
- Storage: Qdrant collections per knowledge domain
- Evaluation: RAGAS framework (faithfulness, relevancy, context recall)

---

## 7. AKS Architecture (Free Tier Optimized)

### Resource Allocation
```
AKS Cluster: genai-aks-poc
├── System Node Pool: systempool
│   ├── VM: Standard_B2s (2 vCPU, 4GB RAM)
│   ├── Nodes: 1 (min) - 2 (max) — autoscale
│   └── Workloads: ArgoCD, Prometheus, Grafana, Vault
│
└── User Node Pool: aiworkload
    ├── VM: Standard_B2s (2 vCPU, 4GB RAM)
    ├── Nodes: 1 (min) - 3 (max) — autoscale
    └── Workloads: RAG API, Qdrant, LLM Gateway, MCP Server
```

### Autoscaling Config
- **Cluster Autoscaler**: enabled (1-5 total nodes)
- **HPA**: CPU 70% threshold, Memory 80% threshold
- **KEDA**: Event-driven scaling on Prometheus metrics (request queue depth)

---

## 8. Security Architecture

```
Internet
   │
   ▼
Azure Load Balancer
   │
   ▼
Ingress Controller (NGINX)
   │  TLS (Let's Encrypt / Self-signed)
   ▼
K8s Network Policy (Calico)
   │  Allow: intra-namespace only
   ▼
Pod Security Standards (Restricted)
   │  Non-root, read-only rootfs
   ▼
Workload Identity (Azure AD)
   │  No stored credentials
   ▼
HashiCorp Vault (Secrets)
   │  Dynamic secrets, auto-rotation
   ▼
Image Scanning (Trivy via GitHub Actions)
```

---

## 9. Observability Design

| Signal | Tool | Key Metrics |
|--------|------|-------------|
| Metrics | Prometheus + Grafana | LLM latency p50/p99, token/s, error rate |
| Logs | Fluentbit → Azure Log Analytics | RAG query logs, embedding latency |
| Traces | OpenTelemetry → Jaeger | End-to-end request trace |
| Alerts | Alertmanager → Email/Slack | LLM latency >5s, error rate >5% |
| Cost | Azure Cost Management | Daily spend vs free tier quota |

---

## 10. Free Tier Constraints & Mitigations

| Constraint | Limit | Mitigation |
|-----------|-------|-----------|
| vCPU quota | 4-8 per region | Use Standard_B2s, limit replicas |
| Public IPs | 3 per sub | Use kubectl proxy for Grafana/ArgoCD |
| Storage | 64GB free | Qdrant persistent volume 10GB |
| LLM Cost | $0 target | Ollama on-cluster (Phi-3 Mini) |
| Azure OpenAI | Pay-per-use | LiteLLM fallback only |
