# GenAI/LLM Pipeline on Azure AKS — POC v3

> **Author**: Sarath Babu | Senior DevOps + AI/MLOps Engineer  
> **Azure Sub**: `7908ea24-a708-4291-be15-98426e3e9ca5`  
> **GitHub**: https://github.com/esarath/ | **DockerHub**: `esarathmails`  
> **K8s Version**: `1.34` (required — do NOT use < 1.29, Workload Identity broken below 1.34 on AKS)

---

## What This POC Proves

| Skill Area | What You Build | Interview Signal |
|---|---|---|
| RAG Pipeline | FastAPI + ChromaDB + Ollama phi3:mini | End-to-end LLM infra ownership |
| GitOps CI/CD | GitHub Actions → ArgoCD → AKS 1.34 | Deployment automation at scale |
| IaC | Terraform — AKS + KV + Workload Identity | Cloud infra as code |
| MCP Integration | Claude ↔ AKS live cluster tools | AI-native ops (cutting edge) |
| Agentic AI | LangGraph ReAct agent with K8s tools | MLOps + autonomous ops |
| Observability | Prometheus + Grafana + LLM metrics | Production readiness |

**Total cost: $0** — AKS Free SKU + free-tier services only.

---

## ⚠️ Critical: Kubernetes Version

```
AKS Kubernetes version: 1.34  ← REQUIRED
```

**Why 1.29+ breaks things (known from our AKS POC experience):**

| Feature | < 1.29 | 1.34 |
|---|---|---|
| Workload Identity GA | ❌ alpha/beta | ✅ stable |
| Key Vault CSI auto-rotate | ❌ flaky | ✅ works |
| Gateway API v1 | ❌ | ✅ |
| Node auto-provisioning | ❌ | ✅ |
| `kubectl` dry-run server-side | partial | ✅ |

**Terraform fix** — already applied in `LLD/terraform/variables.tf`:
```hcl
variable "kubernetes_version" {
  default = "1.34"   # was "1.29.9" — do not downgrade
}
```

**Verify after cluster creation:**
```bash
kubectl version --short
# Server Version: v1.34.x
```

---

## Lightweight POC Stack vs Production Equivalents

> POC = runs free on your laptop or AKS Free SKU.  
> Production = what you cite in interviews as "what I'd use at scale."

| Layer | POC (What You Run) | Production Equivalent |
|---|---|---|
| **Vector DB** | ChromaDB (in-process / single pod) | Qdrant cluster, Weaviate, Pinecone |
| **LLM** | Ollama `phi3:mini` (2B, ~2GB RAM) | Azure OpenAI GPT-4o, Claude claude-sonnet-4-6 |
| **LLM Gateway** | LiteLLM (local) | LiteLLM proxy cluster, Azure APIM |
| **Embeddings** | `all-MiniLM-L6-v2` (384-dim, CPU) | `text-embedding-3-small` (Azure OAI) |
| **Eval** | Manual RAGAS scripts | RAGAS + LangSmith + Weights & Biases |
| **Auth** | Workload Identity + Key Vault CSI | Same — already production pattern |
| **Ingress** | `kubectl port-forward` (free tier limit) | NGINX Ingress + Azure Front Door |
| **Storage** | `managed-csi` 10Gi PVC | Azure NetApp Files, managed disks Premium |
| **Registry** | DockerHub (esarathmails) | Azure Container Registry (ACR) |

---

## Where to Run What — Complete Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│  YOUR LAPTOP (Local)                                                    │
│                                                                         │
│  ✅ Phase 0 — Python learning (learnpython.org, scripts)                │
│  ✅ Phase 1 — RAG pipeline DEV (uvicorn local, ChromaDB in-process)    │
│  ✅ Ollama pull & test  →  ollama run phi3:mini                         │
│  ✅ Terraform plan (az login, tf init/plan — no apply needed local)     │
│  ✅ Docker build + push  →  esarathmails/rag-api:sha                    │
│  ✅ MCP server dev/test  →  python mcp_server.py (stdio)               │
│  ✅ LangGraph agent testing  →  python langgraph_agent.py               │
│  ✅ Prompt template testing  →  python prompt_templates.py              │
│  ✅ RAGAS eval scripts  →  python eval_pipeline.py                      │
│                                                                         │
│  ❌ Do NOT run:  kube-prometheus-stack, ArgoCD, full cluster workloads  │
└─────────────────────────────────────────────────────────────────────────┘
                         │
                         │ git push → GitHub Actions triggers
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  GITHUB ACTIONS (CI — cloud runner, free 2000 min/month)               │
│                                                                         │
│  ✅ ruff lint + mypy + pytest                                           │
│  ✅ Trivy image scan                                                    │
│  ✅ docker buildx build + push → DockerHub                              │
│  ✅ yq update image tag in gitops repo                                  │
│  ✅ Terraform plan (on PR) / apply (on main push)                       │
│                                                                         │
│  ❌ Do NOT: run Ollama here, run ChromaDB here, long-running services   │
└─────────────────────────────────────────────────────────────────────────┘
                         │
                         │ ArgoCD polls gitops repo every 3 min
                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  AKS CLUSTER — aks-genai-poc (K8s 1.34, eastus, Free SKU)             │
│  Resource Group: rg-genai-poc                                           │
│                                                                         │
│  System Pool (Standard_B2s, 1 node — fixed):                           │
│    ✅ ArgoCD                                                            │
│    ✅ kube-system components                                            │
│    ✅ Key Vault CSI driver                                              │
│                                                                         │
│  AI Workload Pool (Standard_B2s, autoscale 1→3):                       │
│    ✅ RAG API (FastAPI + ChromaDB, 1 replica → HPA up to 4)            │
│    ✅ Ollama (phi3:mini, 2GB RAM, 10Gi PVC for model cache)            │
│    ✅ MCP Server (when Claude integration tested)                       │
│                                                                         │
│  Monitoring namespace:                                                  │
│    ✅ kube-prometheus-stack (Prometheus + Grafana)                      │
│    ✅ Alert rules (18 genai-specific rules)                             │
│                                                                         │
│  Access via kubectl port-forward (free tier = max 3 public IPs):       │
│    Grafana    → kubectl port-forward svc/grafana 3000:80 -n monitoring │
│    ArgoCD     → kubectl port-forward svc/argocd-server 8080:443        │
│    RAG API    → kubectl port-forward svc/rag-api 8000:8000 -n genai   │
│    Prometheus → kubectl port-forward svc/prometheus 9090:9090          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Timeline — 9 Weeks @ 3–4 hrs/day

> Aligned to `Sarath_AIMLOps_Roadmap.html` — target: portfolio complete 12 Aug 2026

### Phase 0 — Python Foundations (Week 1 | LOCAL)
**Where**: Laptop  
**Tools**: Python 3.11, VS Code, learnpython.org

```
Day 1-2:  learnpython.org modules 1–9 (done ✅)
Day 3:    Functions, classes, decorators → write rag_utils.py skeleton
Day 4:    async/await + httpx → call Ollama from Python locally
Day 5:    pytest basics → write 3 tests for rag_utils.py
```

### Phase 1 — RAG Pipeline DEV (Weeks 2–3 | LOCAL → AKS)
**Where**: Laptop for dev, AKS for integration test  
**Tools**: FastAPI, ChromaDB, Ollama phi3:mini, sentence-transformers

```
Week 2 Day 1:  ollama pull phi3:mini  →  curl localhost:11434/api/chat
Week 2 Day 2:  pip install -r requirements.txt  →  uvicorn rag_api:app
Week 2 Day 3:  POST /ingest with sample K8s docs  →  verify ChromaDB
Week 2 Day 4:  POST /query  →  get grounded answer  →  check /metrics
Week 2 Day 5:  docker build + push esarathmails/rag-api:v1

Week 3 Day 1:  terraform init + apply  →  aks-genai-poc (K8s 1.34)
Week 3 Day 2:  kubectl apply namespaces/RBAC  →  helm install rag-api
Week 3 Day 3:  port-forward + smoke test /health + /query on AKS
Week 3 Day 4:  ingest 10 real documents (K8s docs, ArgoCD guide)
Week 3 Day 5:  GitHub Actions CI push → verify ArgoCD syncs
```

### Phase 2 — MCP + Agentic (Week 4 | LOCAL + AKS)
**Where**: MCP server runs LOCAL (stdio), talks to AKS via kubectl proxy  
**Tools**: Anthropic MCP SDK, LangGraph, kubectl proxy

```
Day 1:  kubectl proxy --port=8001 &  →  curl localhost:8001/api/v1/nodes
Day 2:  python mcp_server.py  →  test rag_query tool locally
Day 3:  python langgraph_agent.py  →  "what pods are running in genai ns?"
Day 4:  wire agent → MCP → AKS live  →  agent reports cluster health
Day 5:  document MCP tool call traces for portfolio
```

### Phase 3 — Observability (Week 5 | AKS)
**Where**: AKS cluster only  
**Tools**: kube-prometheus-stack, custom alert rules, Grafana dashboards

```
Day 1:  helm install kube-prometheus-stack (v58.2.2)
Day 2:  kubectl apply -f Observability/prometheus/genai-alert-rules.yaml
Day 3:  port-forward Grafana 3000:80  →  import dashboard ConfigMap
Day 4:  generate load → watch metrics (latency, retrieval score, tokens)
Day 5:  screenshot dashboard → add to portfolio README
```

### Phase 4 — LLMOps + Eval (Week 6 | LOCAL)
**Where**: Laptop (eval scripts call AKS RAG API via port-forward)  
**Tools**: RAGAS eval scripts, Python async eval pipeline

```
Day 1:  port-forward RAG API  →  run eval_pipeline.py
Day 2:  review faithfulness + relevancy scores
Day 3:  tune chunk_size / overlap / top_k  →  re-eval
Day 4:  document baseline vs tuned metrics
Day 5:  write LLMOps section of portfolio README
```

### Phase 5 — AI-102 + Azure AI Foundry (Weeks 7–8 | Azure Portal + LOCAL)
**Where**: Azure Portal (free trial features), laptop for SDK calls  
**Tools**: Azure AI Foundry, az cli, python openai SDK

```
Week 7:  AI-102 study (Microsoft Learn) + practice tests
Week 8:  Azure AI Foundry project → test GPT-4o as LLM fallback for RAG API
         Update LiteLLM config to route to Azure OpenAI
         Document cost comparison: Ollama ($0) vs Azure OAI (~$0.01/query)
```

### Phase 6 — Portfolio Hardening + Job Applications (Week 9)
**Where**: GitHub, LinkedIn, applications  

```
Day 1-2:  Record 3-min Loom demo: RAG query → Grafana → ArgoCD sync
Day 3:    Push all code to github.com/esarath/genai-aks-poc
Day 4:    Update SarathBabu_DevOps_AI_Resume_2026.docx with this POC
Day 5:    Apply to 5 target roles — cite POC GitHub URL
```

---

## Quick Start (Day 1 Essentials)

### Step 1 — Laptop: Install & Verify Tools
```bash
# Python
python3 --version        # Need 3.11+
pip install fastapi uvicorn chromadb sentence-transformers litellm httpx prometheus-client pydantic

# Ollama (runs LLM locally, free)
curl -fsSL https://ollama.ai/install.sh | sh
ollama pull phi3:mini    # ~2GB download, one-time
ollama run phi3:mini "Explain Kubernetes in 2 sentences"

# Docker
docker --version
docker login -u esarathmails

# Azure + Terraform + kubectl
az --version && terraform --version && kubectl version --client
```

### Step 2 — Laptop: Run RAG API Locally (No K8s needed)
```bash
cd AI-MLOps/rag-pipeline
OLLAMA_HOST=http://localhost:11434 uvicorn rag_api:app --port 8000

# Ingest sample document
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text": "Kubernetes is a container orchestration platform. It schedules pods across nodes. ArgoCD is a GitOps tool for Kubernetes.", "metadata": {"source": "test"}}'

# Query it
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query": "What is ArgoCD?", "top_k": 3}'
```

### Step 3 — AKS: Deploy Infrastructure
```bash
# Set subscription
az login
az account set --subscription 7908ea24-a708-4291-be15-98426e3e9ca5

# Terraform state backend (run once)
az group create -n rg-tfstate -l eastus
az storage account create -n sttfstatesarath001 -g rg-tfstate -l eastus --sku Standard_LRS
az storage container create -n tfstate --account-name sttfstatesarath001

# Deploy AKS (K8s 1.34)
cd LLD/terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan

# Get credentials
az aks get-credentials --resource-group rg-genai-poc --name aks-genai-poc

# Verify K8s version
kubectl version --short   # Must show v1.34.x
kubectl get nodes
```

### Step 4 — AKS: Deploy Workloads via ArgoCD
```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl rollout status deployment/argocd-server -n argocd --timeout=180s

# Get ArgoCD admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d

# Access ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443 &
# Open: https://localhost:8080  |  user: admin

# Deploy all apps
kubectl apply -f LLD/argocd-manifests/argocd-apps.yaml

# Watch sync status
kubectl get applications -n argocd
```

### Step 5 — AKS: Test RAG API on Cluster
```bash
# Wait for pods
kubectl get pods -n genai -w

# Port-forward RAG API
kubectl port-forward svc/rag-api 8000:8000 -n genai &

# Smoke test
curl http://localhost:8000/health
curl -X POST http://localhost:8000/ingest \
  -H 'Content-Type: application/json' \
  -d '{"text":"Kubernetes 1.34 includes stable Workload Identity and Gateway API v1.", "metadata":{"source":"k8s-docs"}}'
curl -X POST http://localhost:8000/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"What is new in Kubernetes 1.34?","top_k":3}'
```

---

## Project Structure

```
GenAI-LLM-AKS-POC/
├── README.md                                ← YOU ARE HERE
├── GenAI-AKS-POC-Master-Guide.html         ← Interactive 10-tab guide
│
├── HLD/
│   └── HLD-GenAI-AKS-Architecture.md       ← Architecture + data flow diagrams
│
├── LLD/
│   ├── terraform/                           ← AKS 1.34 + VNet + KV + Workload ID
│   │   ├── main.tf
│   │   ├── variables.tf                     ← kubernetes_version = "1.34"
│   │   └── outputs.tf
│   ├── github-actions/
│   │   ├── ci-rag-api.yml                  ← lint → scan → build → gitops → test
│   │   └── terraform-aks.yml               ← OIDC plan/apply
│   ├── helm-charts/
│   │   └── rag-api-values.yaml             ← HPA, tolerations, workload identity
│   ├── argocd-manifests/
│   │   └── argocd-apps.yaml                ← AppProject + 5 apps (auto-sync)
│   └── k8s-manifests/
│       └── namespace-rbac-secrets.yaml     ← RBAC, NetworkPolicy, SecretProviderClass
│
├── AI-MLOps/
│   ├── rag-pipeline/
│   │   ├── rag_api.py                      ← FastAPI RAG (ChromaDB POC backend)
│   │   ├── Dockerfile                      ← multi-stage, non-root, slim
│   │   └── requirements.txt               ← lightweight stack, prod notes inline
│   ├── mcp-integration/
│   │   └── mcp_server.py                  ← 8 tools: RAG query + K8s ops
│   ├── agentic-workflows/
│   │   └── langgraph_agent.py             ← ReAct agent, max 10 iter, K8s tools
│   ├── prompt-engineering/
│   │   └── prompt_templates.py            ← 8 templates incl. CoT, HyDE, safety
│   └── embeddings-eval/
│       └── eval_pipeline.py               ← async RAGAS-style eval, 4 metrics
│
├── Observability/
│   ├── prometheus/
│   │   └── genai-alert-rules.yaml         ← 18 rules: availability, perf, quality
│   ├── grafana/
│   │   └── genai-dashboard.yaml           ← K8s ConfigMap, auto-import
│   └── azure-monitor/
│       └── azure-monitor-config.yaml      ← Container Insights + remote_write
│
└── Docs/
    └── CLI-Deployment-Guide.md            ← Full CLI, day-by-day, 4-week plan
```

---

## GitHub Secrets Required (GitHub Actions)

Set these in `https://github.com/esarath/genai-aks-poc/settings/secrets/actions`:

| Secret Name | Value | Used By |
|---|---|---|
| `DOCKERHUB_TOKEN` | DockerHub access token | `ci-rag-api.yml` — image push |
| `GITOPS_PAT` | GitHub PAT (repo write) | `ci-rag-api.yml` — update gitops repo |
| `AZURE_CLIENT_ID` | SP client ID (OIDC) | Both workflows — `az login` |
| `AZURE_TENANT_ID` | Azure tenant ID | Both workflows — `az login` |
| `QDRANT_API_KEY` | Qdrant key (can be empty for POC) | `terraform-aks.yml` — KV secret |

---

## Known Issues & Fixes

| Issue | Root Cause | Fix |
|---|---|---|
| Workload Identity not injecting tokens | K8s < 1.34 | Use `kubernetes_version = "1.34"` |
| CSI driver secret rotation failing | K8s 1.28–1.29 bug | Upgrade to 1.34 |
| Grafana/Prometheus UI unreachable | AKS Free tier 3 public IP limit | Use `kubectl port-forward` |
| Ollama OOM killed | Default memory limit too low | Set `memory: "2.5Gi"` in values |
| ChromaDB data loss on pod restart | No PVC in dev mode | Add PVC or use `--path /data` |
| ArgoCD not syncing | Gitops repo PAT expired | Rotate `GITOPS_PAT` secret |

---

## Portfolio Demo Script (3 min Loom / Interview)

```
0:00  "I built a production-pattern GenAI pipeline on AKS 1.34 — zero cost, 
       full observability."

0:20  Show: kubectl get pods -n genai  →  rag-api + ollama running

0:40  Show: curl /ingest with K8s docs  →  ChromaDB stores chunks

1:00  Show: curl /query "What is ArgoCD GitOps?"  →  grounded answer + sources

1:20  Show: Grafana dashboard — RAG latency, retrieval scores, active queries

1:45  Show: ArgoCD UI — rag-api app healthy, last sync timestamp

2:10  Show: GitHub Actions — 5-job CI pipeline, Trivy scan clean

2:35  "In production I'd replace ChromaDB with Qdrant cluster, phi3:mini with
       GPT-4o via Azure OpenAI, and add A/B evaluation via LangSmith."

3:00  End — GitHub URL on screen: github.com/esarath/genai-aks-poc
```

---

## Links

| Resource | URL |
|---|---|
| App repo | https://github.com/esarath/genai-aks-poc |
| GitOps repo | https://github.com/esarath/genai-aks-gitops |
| DockerHub | https://hub.docker.com/u/esarathmails |
| Interactive Guide | `GenAI-AKS-POC-Master-Guide.html` |
| CLI Guide | `Docs/CLI-Deployment-Guide.md` |
| Learning Roadmap | `Sarath_AIMLOps_Roadmap.html` |
