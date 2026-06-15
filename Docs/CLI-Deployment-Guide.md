# Step-by-Step CLI Deployment Guide
# GenAI/LLM Pipeline on Azure AKS
**Author**: Sarath Babu | Senior DevOps + AI/MLOps Architect  
**GitHub**: https://github.com/esarath/  
**DockerHub**: esarathmails  
**Azure Sub**: 7908ea24-a708-4291-be15-98426e3e9ca5

---

## PRE-REQUISITES INSTALLATION

```bash
# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az --version

# Install kubectl
az aks install-cli
kubectl version --client

# Install Terraform
wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
sudo apt-get install -y terraform
terraform --version

# Install Helm
curl https://baltocdn.com/helm/signing.asc | gpg --dearmor | sudo tee /usr/share/keyrings/helm.gpg > /dev/null
sudo apt-get install -y helm
helm version

# Install ArgoCD CLI
curl -sSL -o argocd-linux-amd64 https://github.com/argoproj/argo-cd/releases/latest/download/argocd-linux-amd64
sudo install -m 555 argocd-linux-amd64 /usr/local/bin/argocd

# Python tools
pip install langchain langchain-openai langgraph qdrant-client \
            sentence-transformers ragas fastapi uvicorn \
            anthropic mcp httpx prometheus-client

# Docker
curl -fsSL https://get.docker.com | bash
docker login -u esarathmails  # enter DockerHub token
```

---

## WEEK 1: INFRASTRUCTURE SETUP

### Day 1: Azure Login & Resource Preparation

```bash
# Login to Azure
az login
az account set --subscription 7908ea24-a708-4291-be15-98426e3e9ca5
az account show --output table

# Register required providers
az provider register --namespace Microsoft.ContainerService
az provider register --namespace Microsoft.KeyVault
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ManagedIdentity

# Wait for registration (check status)
az provider show -n Microsoft.ContainerService --query registrationState

# Create Terraform state storage
az group create --name rg-genai-tfstate --location eastus

az storage account create \
  --name stgenaitfstate$RANDOM \
  --resource-group rg-genai-tfstate \
  --location eastus \
  --sku Standard_LRS \
  --kind StorageV2

az storage container create \
  --name tfstate \
  --account-name <storage-account-name>

# Note the storage account name for backend config
```

### Day 2: Terraform Init & Plan

```bash
cd GenAI-LLM-AKS-POC/LLD/terraform

# Initialize Terraform
terraform init \
  -backend-config="storage_account_name=<your-storage-account>" \
  -backend-config="resource_group_name=rg-genai-tfstate"

# Validate
terraform validate
terraform fmt -recursive

# Plan (review before apply)
terraform plan \
  -var="azure_openai_api_key=${AZURE_OPENAI_KEY}" \
  -var="dockerhub_token=${DOCKERHUB_TOKEN}" \
  -out=tfplan

# Review plan output carefully
terraform show tfplan | less
```

### Day 3: Deploy AKS Cluster

```bash
# Apply Terraform
terraform apply tfplan

# Get outputs
AKS_NAME=$(terraform output -raw aks_cluster_name)
RG_NAME=$(terraform output -raw resource_group_name)
KV_NAME=$(terraform output -raw key_vault_name)

echo "AKS: $AKS_NAME | RG: $RG_NAME | KV: $KV_NAME"

# Configure kubectl
az aks get-credentials \
  --resource-group $RG_NAME \
  --name $AKS_NAME \
  --subscription 7908ea24-a708-4291-be15-98426e3e9ca5

# Verify cluster
kubectl get nodes -o wide
kubectl get namespaces
kubectl top nodes

# Check autoscaler
kubectl -n kube-system get deployment cluster-autoscaler
kubectl -n kube-system logs -l app=cluster-autoscaler --tail=20
```

### Day 4: Namespace & RBAC Setup

```bash
# Create namespaces
kubectl create namespace genai-rag
kubectl create namespace genai-llm
kubectl create namespace genai-observe
kubectl create namespace vault
kubectl create namespace argocd

# Label namespaces
kubectl label namespace genai-rag env=poc project=genai
kubectl label namespace genai-llm env=poc project=genai

# Create resource quotas (free tier friendly)
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ResourceQuota
metadata:
  name: genai-quota
  namespace: genai-rag
spec:
  hard:
    requests.cpu: "2"
    requests.memory: 4Gi
    limits.cpu: "4"
    limits.memory: 8Gi
    pods: "20"
    persistentvolumeclaims: "5"
EOF

# Create DockerHub image pull secret
kubectl create secret docker-registry dockerhub-secret \
  --docker-username=esarathmails \
  --docker-password=${DOCKERHUB_TOKEN} \
  --docker-email=esarathmails@gmail.com \
  --namespace=genai-rag

kubectl create secret docker-registry dockerhub-secret \
  --docker-username=esarathmails \
  --docker-password=${DOCKERHUB_TOKEN} \
  --docker-email=esarathmails@gmail.com \
  --namespace=genai-llm
```

### Day 5: Install ArgoCD

```bash
# Install ArgoCD
kubectl apply -n argocd -f \
  https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready
kubectl -n argocd rollout status deployment/argocd-server

# Get admin password
ARGOCD_PASS=$(kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d)
echo "ArgoCD Password: $ARGOCD_PASS"

# Access via kubectl proxy (free tier - no extra public IP)
kubectl port-forward svc/argocd-server -n argocd 8080:443 &

# Login ArgoCD CLI
argocd login localhost:8080 \
  --username admin \
  --password $ARGOCD_PASS \
  --insecure

# Connect GitHub repo
argocd repo add https://github.com/esarath/genai-aks-gitops \
  --username esarath \
  --password ${GITHUB_PAT}

# Apply ArgoCD apps
kubectl apply -f GenAI-LLM-AKS-POC/LLD/argocd-manifests/argocd-apps.yaml
```

---

## WEEK 2: CONTAINERIZATION & REGISTRY

### Day 1-2: Build & Push Docker Images

```bash
cd GenAI-LLM-AKS-POC/AI-MLOps/rag-pipeline

# Create Dockerfile for RAG API
cat > Dockerfile <<'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -r -u 1001 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

# Build image
docker build -t esarathmails/rag-api:latest .
docker build -t esarathmails/rag-api:v1.0.0 .

# Security scan before push
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  aquasec/trivy:latest image esarathmails/rag-api:latest

# Push to DockerHub
docker push esarathmails/rag-api:latest
docker push esarathmails/rag-api:v1.0.0

# Build embedding service
cd ../embeddings
docker build -t esarathmails/embedding-service:latest .
docker push esarathmails/embedding-service:latest

# Build MCP server
cd ../mcp-integration
docker build -t esarathmails/mcp-server:latest .
docker push esarathmails/mcp-server:latest
```

### Day 3-4: Deploy Qdrant Vector DB

```bash
# Add Qdrant Helm repo
helm repo add qdrant https://qdrant.github.io/qdrant-helm
helm repo update

# Install Qdrant
helm upgrade --install qdrant qdrant/qdrant \
  --namespace genai-rag \
  --set replicaCount=1 \
  --set persistence.enabled=true \
  --set persistence.size=10Gi \
  --set resources.requests.memory=512Mi \
  --set resources.requests.cpu=250m \
  --set resources.limits.memory=1Gi \
  --set tolerations[0].key=workload \
  --set tolerations[0].value=ai \
  --set tolerations[0].effect=NoSchedule

# Verify
kubectl -n genai-rag get pods -l app.kubernetes.io/name=qdrant
kubectl -n genai-rag get pvc

# Test Qdrant (via port-forward)
kubectl -n genai-rag port-forward svc/qdrant 6333:6333 &
curl http://localhost:6333/healthz
curl http://localhost:6333/collections

# Create initial collection
curl -X PUT http://localhost:6333/collections/genai-knowledge \
  -H 'Content-Type: application/json' \
  -d '{
    "vectors": {
      "size": 384,
      "distance": "Cosine"
    }
  }'
```

### Day 5: Deploy LLM Gateway (Ollama + LiteLLM)

```bash
# Deploy Ollama (runs Phi-3 Mini on CPU — free!)
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ollama
  namespace: genai-llm
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ollama
  template:
    metadata:
      labels:
        app: ollama
    spec:
      tolerations:
        - key: workload
          value: ai
          effect: NoSchedule
      containers:
        - name: ollama
          image: ollama/ollama:latest
          ports:
            - containerPort: 11434
          resources:
            requests:
              memory: "2Gi"
              cpu: "500m"
            limits:
              memory: "3Gi"
              cpu: "2000m"
          volumeMounts:
            - name: ollama-data
              mountPath: /root/.ollama
      volumes:
        - name: ollama-data
          persistentVolumeClaim:
            claimName: ollama-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: ollama
  namespace: genai-llm
spec:
  selector:
    app: ollama
  ports:
    - port: 11434
      targetPort: 11434
EOF

# Wait for Ollama then pull Phi-3 Mini
kubectl -n genai-llm wait --for=condition=ready pod -l app=ollama --timeout=120s
kubectl -n genai-llm exec -it deploy/ollama -- ollama pull phi3:mini

# Verify model loaded
kubectl -n genai-llm exec -it deploy/ollama -- ollama list
```

---

## WEEK 3: CI/CD + GITOPS + RAG DEPLOYMENT

### Day 1-2: Configure GitHub Actions Secrets

```bash
# Set GitHub repo secrets via CLI (requires gh CLI)
gh auth login

REPO="esarath/genai-aks-poc"

gh secret set DOCKERHUB_TOKEN --body "$DOCKERHUB_TOKEN" --repo $REPO
gh secret set GITOPS_PAT --body "$GITHUB_PAT" --repo $REPO
gh secret set AZURE_CLIENT_ID --body "$ARM_CLIENT_ID" --repo $REPO
gh secret set AZURE_TENANT_ID --body "$ARM_TENANT_ID" --repo $REPO
gh secret set ANTHROPIC_API_KEY --body "$ANTHROPIC_API_KEY" --repo $REPO
gh secret set AZURE_OPENAI_API_KEY --body "$AZURE_OPENAI_API_KEY" --repo $REPO

# Trigger first CI run
git add .
git commit -m "ci: initial GenAI pipeline deployment"
git push origin main

# Monitor workflow
gh run list --repo $REPO
gh run watch --repo $REPO
```

### Day 3: Deploy RAG API

```bash
# Deploy RAG API
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-api
  namespace: genai-rag
spec:
  replicas: 1
  selector:
    matchLabels:
      app: rag-api
  template:
    metadata:
      labels:
        app: rag-api
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
        prometheus.io/path: "/metrics"
    spec:
      imagePullSecrets:
        - name: dockerhub-secret
      tolerations:
        - key: workload
          value: ai
          effect: NoSchedule
      containers:
        - name: rag-api
          image: esarathmails/rag-api:latest
          ports:
            - containerPort: 8000
          env:
            - name: QDRANT_URL
              value: "http://qdrant:6333"
            - name: LLM_BASE_URL
              value: "http://ollama.genai-llm:11434"
            - name: LLM_MODEL
              value: "phi3:mini"
            - name: EMBEDDING_SERVICE_URL
              value: "http://embedding-service:8001"
          resources:
            requests:
              memory: "256Mi"
              cpu: "200m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 15
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 30
            periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata:
  name: rag-api
  namespace: genai-rag
spec:
  selector:
    app: rag-api
  ports:
    - port: 8000
      targetPort: 8000
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: rag-api-hpa
  namespace: genai-rag
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: rag-api
  minReplicas: 1
  maxReplicas: 3
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Resource
      resource:
        name: memory
        target:
          type: Utilization
          averageUtilization: 80
EOF

# Verify
kubectl -n genai-rag get all
kubectl -n genai-rag describe deployment rag-api

# Test RAG API
kubectl -n genai-rag port-forward svc/rag-api 8000:8000 &

curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is Kubernetes autoscaling?", "top_k": 3}'
```

### Day 4-5: Ingest Documents & Test Pipeline

```bash
# Ingest sample documents into knowledge base
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "documents": [
      "AKS Cluster Autoscaler automatically adjusts the number of nodes in a cluster when pods fail to schedule due to insufficient resources. It works with Horizontal Pod Autoscaler (HPA) which scales pod replicas based on CPU and memory metrics.",
      "RAG (Retrieval-Augmented Generation) combines information retrieval with text generation. The pipeline embeds the user query, retrieves relevant document chunks from a vector database like Qdrant, then feeds the context to an LLM to generate a grounded response.",
      "LangChain is a framework for building LLM-powered applications. It provides chains, agents, and tools to orchestrate complex AI workflows. LangGraph extends this with graph-based stateful agent workflows.",
      "Model Context Protocol (MCP) is an open protocol by Anthropic that standardizes how AI models connect to external tools and data sources. It enables Claude to interact with APIs, databases, and code execution environments."
    ],
    "metadata": [
      {"source": "k8s-docs", "topic": "autoscaling"},
      {"source": "genai-docs", "topic": "rag"},
      {"source": "langchain-docs", "topic": "orchestration"},
      {"source": "anthropic-docs", "topic": "mcp"}
    ]
  }'

# Test queries
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "How does RAG work?", "top_k": 2}' | jq .answer

curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is MCP protocol?", "top_k": 2}' | jq .answer
```

---

## WEEK 4: MCP + AGENTS + OBSERVABILITY + TESTING

### Day 1: Deploy MCP Server

```bash
# Store Anthropic API key in K8s secret
kubectl create secret generic mcp-secrets \
  --from-literal=anthropic-api-key=${ANTHROPIC_API_KEY} \
  --namespace genai-rag

# Deploy MCP Server
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-server
  namespace: genai-rag
spec:
  replicas: 1
  selector:
    matchLabels:
      app: mcp-server
  template:
    metadata:
      labels:
        app: mcp-server
    spec:
      imagePullSecrets:
        - name: dockerhub-secret
      containers:
        - name: mcp-server
          image: esarathmails/mcp-server:latest
          env:
            - name: RAG_API_URL
              value: "http://rag-api:8000"
            - name: ANTHROPIC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: mcp-secrets
                  key: anthropic-api-key
            - name: K8S_NAMESPACE
              value: "genai-rag"
          resources:
            requests:
              memory: "128Mi"
              cpu: "100m"
            limits:
              memory: "256Mi"
              cpu: "300m"
EOF

# Test MCP connectivity
kubectl -n genai-rag logs -l app=mcp-server --follow
```

### Day 2: Deploy Observability Stack

```bash
# Install kube-prometheus-stack
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm upgrade --install kube-prometheus-stack \
  prometheus-community/kube-prometheus-stack \
  --namespace genai-observe \
  --create-namespace \
  --set grafana.adminPassword=genai-poc-grafana \
  --set prometheus.prometheusSpec.retention=7d \
  --set alertmanager.enabled=true \
  --wait

# Apply custom alerting rules
kubectl apply -f GenAI-LLM-AKS-POC/Observability/prometheus/genai-alert-rules.yaml

# Access Grafana (kubectl proxy — free tier workaround)
kubectl -n genai-observe port-forward svc/kube-prometheus-stack-grafana 3000:80 &
echo "Grafana: http://localhost:3000 | admin / genai-poc-grafana"

# Access Prometheus
kubectl -n genai-observe port-forward svc/kube-prometheus-stack-prometheus 9090:9090 &
echo "Prometheus: http://localhost:9090"

# Verify metrics from RAG API
curl -s "http://localhost:9090/api/v1/query?query=rag_requests_total" | jq .

# Check alert rules loaded
curl -s "http://localhost:9090/api/v1/rules" | jq '.data.groups[].name'
```

### Day 3: Run Evaluation Pipeline

```bash
# Run RAGAS evaluation on RAG pipeline
pip install ragas datasets

python3 << 'EOF'
import asyncio
import json
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_recall
from datasets import Dataset
import httpx

async def evaluate_rag():
    test_cases = [
        {
            "question": "What is Kubernetes autoscaling?",
            "ground_truth": "Kubernetes autoscaling automatically adjusts resources based on demand using HPA for pods and Cluster Autoscaler for nodes."
        },
        {
            "question": "How does RAG work?",
            "ground_truth": "RAG retrieves relevant documents from a knowledge base and feeds them as context to an LLM to generate grounded answers."
        },
    ]
    
    results = []
    async with httpx.AsyncClient(timeout=60.0) as client:
        for tc in test_cases:
            resp = await client.post(
                "http://localhost:8000/query",
                json={"query": tc["question"], "top_k": 3}
            )
            data = resp.json()
            results.append({
                "question": tc["question"],
                "answer": data["answer"],
                "contexts": [c["content"] for c in data["retrieved_chunks"]],
                "ground_truth": tc["ground_truth"],
                "latency_ms": data["latency_ms"]
            })
    
    # Print results
    for r in results:
        print(f"\nQ: {r['question']}")
        print(f"A: {r['answer'][:200]}...")
        print(f"Latency: {r['latency_ms']:.0f}ms | Sources: {len(r['contexts'])}")
    
    print("\nEvaluation complete!")

asyncio.run(evaluate_rag())
EOF
```

### Day 4: End-to-End Integration Test

```bash
# Run full integration test
python3 -m pytest GenAI-LLM-AKS-POC/tests/integration/ -v \
  --base-url=http://localhost:8000 \
  --tb=short \
  --html=test-report.html

# Load test with k6 (optional)
docker run --rm -i grafana/k6 run - <<'EOF'
import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '30s', target: 5 },
    { duration: '1m', target: 10 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<30000'],  // 30s for LLM
    http_req_failed: ['rate<0.05'],
  },
};

export default function () {
  const res = http.post('http://localhost:8000/query', 
    JSON.stringify({ query: 'What is RAG?', top_k: 3 }),
    { headers: { 'Content-Type': 'application/json' } }
  );
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(2);
}
EOF
```

### Day 5: Final Verification & Documentation

```bash
# Final cluster status check
echo "=== CLUSTER STATUS ==="
kubectl get nodes -o wide

echo "=== GENAI PODS ==="
kubectl get pods -n genai-rag
kubectl get pods -n genai-llm
kubectl get pods -n genai-observe
kubectl get pods -n argocd

echo "=== HPA STATUS ==="
kubectl get hpa -A

echo "=== ARGOCD APPS ==="
argocd app list

echo "=== AUTOSCALER STATUS ==="
kubectl -n kube-system logs -l app=cluster-autoscaler --tail=10

echo "=== QDRANT COLLECTIONS ==="
curl -s http://localhost:6333/collections | jq .

echo "=== RAG API HEALTH ==="
curl -s http://localhost:8000/health | jq .

echo "=== KEY METRICS (Prometheus) ==="
curl -s "http://localhost:9090/api/v1/query?query=rag_requests_total" | jq '.data.result'
curl -s "http://localhost:9090/api/v1/query?query=histogram_quantile(0.99,rate(rag_request_duration_seconds_bucket[5m]))" | jq '.data.result'

echo "✅ GenAI AKS POC Deployment Complete!"
echo "GitHub: https://github.com/esarath/genai-aks-poc"
echo "DockerHub: https://hub.docker.com/u/esarathmails"
```

---

## SECRETS MANAGEMENT REFERENCE

```bash
# Store secrets in Azure Key Vault
az keyvault secret set --vault-name $KV_NAME \
  --name "openai-api-key" --value "$AZURE_OPENAI_API_KEY"
az keyvault secret set --vault-name $KV_NAME \
  --name "anthropic-api-key" --value "$ANTHROPIC_API_KEY"
az keyvault secret set --vault-name $KV_NAME \
  --name "dockerhub-token" --value "$DOCKERHUB_TOKEN"

# Create K8s SecretProviderClass for Key Vault
cat <<EOF | kubectl apply -f -
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: genai-kv-secrets
  namespace: genai-rag
spec:
  provider: azure
  secretObjects:
    - secretName: genai-api-secrets
      type: Opaque
      data:
        - objectName: openai-api-key
          key: AZURE_OPENAI_API_KEY
        - objectName: anthropic-api-key
          key: ANTHROPIC_API_KEY
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    keyvaultName: "$KV_NAME"
    objects: |
      array:
        - |
          objectName: openai-api-key
          objectType: secret
        - |
          objectName: anthropic-api-key
          objectType: secret
    tenantId: "$ARM_TENANT_ID"
EOF
```

---

## TROUBLESHOOTING QUICK REFERENCE

```bash
# Pod not starting
kubectl -n genai-rag describe pod <pod-name>
kubectl -n genai-rag logs <pod-name> --previous

# Node not ready
kubectl describe node <node-name>
kubectl get events -n kube-system --sort-by=.lastTimestamp

# ArgoCD out of sync
argocd app sync rag-api
argocd app get rag-api

# Qdrant unreachable
kubectl -n genai-rag exec -it deploy/rag-api -- curl http://qdrant:6333/healthz

# LLM timeout
kubectl -n genai-llm logs -l app=ollama --tail=50
kubectl -n genai-llm exec -it deploy/ollama -- ollama list

# HPA not scaling
kubectl -n genai-rag describe hpa rag-api-hpa
kubectl -n kube-system logs -l app=metrics-server --tail=20
```
