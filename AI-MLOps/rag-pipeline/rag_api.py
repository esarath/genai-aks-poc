"""
GenAI RAG Pipeline - FastAPI Application
Author: Sarath Babu | Senior DevOps + AI/MLOps Architect
GitHub: https://github.com/esarath/genai-aks-poc
DockerHub: esarathmails/rag-api
"""

import os
import time
import logging
from contextlib import asynccontextmanager
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from prometheus_client import (
    Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST
)
from fastapi.responses import Response

# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s'
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "genai-knowledge")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://llm-gateway:4000")
LLM_MODEL = os.getenv("LLM_MODEL", "phi3:mini")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_SERVICE_URL = os.getenv("EMBEDDING_SERVICE_URL", "http://embedding-service:8001")
TOP_K = int(os.getenv("TOP_K", "5"))
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.7"))

# ─────────────────────────────────────────────
# Prometheus Metrics
# ─────────────────────────────────────────────
REQUEST_COUNT = Counter(
    'rag_requests_total',
    'Total RAG API requests',
    ['method', 'endpoint', 'status']
)
REQUEST_LATENCY = Histogram(
    'rag_request_duration_seconds',
    'RAG request latency',
    ['endpoint'],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0]
)
LLM_LATENCY = Histogram(
    'rag_llm_inference_seconds',
    'LLM inference latency',
    ['model'],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)
RETRIEVAL_LATENCY = Histogram(
    'rag_retrieval_seconds',
    'Vector DB retrieval latency',
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0]
)
RETRIEVAL_SCORE = Histogram(
    'rag_retrieval_score',
    'Similarity scores of retrieved documents',
    buckets=[0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
)
TOKEN_COUNT = Counter(
    'rag_tokens_total',
    'Total tokens processed',
    ['type']  # prompt, completion
)
ACTIVE_QUERIES = Gauge(
    'rag_active_queries',
    'Currently processing RAG queries'
)

# ─────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="User query")
    collection: Optional[str] = Field(None, description="Qdrant collection name")
    top_k: Optional[int] = Field(5, ge=1, le=20)
    mode: Optional[str] = Field("naive", description="RAG mode: naive|advanced|agentic")
    system_prompt: Optional[str] = None
    temperature: Optional[float] = Field(0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(1024, ge=64, le=4096)

class DocumentChunk(BaseModel):
    id: str
    content: str
    score: float
    metadata: dict

class QueryResponse(BaseModel):
    query: str
    answer: str
    retrieved_chunks: List[DocumentChunk]
    latency_ms: float
    model: str
    tokens_used: int
    rag_mode: str

class IngestRequest(BaseModel):
    documents: List[str]
    metadata: Optional[List[dict]] = None
    collection: Optional[str] = None
    chunk_size: Optional[int] = 512
    chunk_overlap: Optional[int] = 50

class HealthResponse(BaseModel):
    status: str
    version: str
    components: dict

# ─────────────────────────────────────────────
# RAG Engine
# ─────────────────────────────────────────────
class RAGEngine:
    def __init__(self):
        self.qdrant_url = QDRANT_URL
        self.llm_url = LLM_BASE_URL
        self.embedding_url = EMBEDDING_SERVICE_URL

    async def get_embedding(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.embedding_url}/embed",
                json={"text": text}
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    async def retrieve(
        self,
        query_embedding: List[float],
        collection: str,
        top_k: int
    ) -> List[DocumentChunk]:
        start = time.time()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{self.qdrant_url}/collections/{collection}/points/search",
                json={
                    "vector": query_embedding,
                    "limit": top_k,
                    "with_payload": True,
                    "score_threshold": SIMILARITY_THRESHOLD
                }
            )
            resp.raise_for_status()
            results = resp.json()["result"]

        latency = time.time() - start
        RETRIEVAL_LATENCY.observe(latency)

        chunks = []
        for r in results:
            RETRIEVAL_SCORE.observe(r["score"])
            chunks.append(DocumentChunk(
                id=str(r["id"]),
                content=r["payload"].get("content", ""),
                score=r["score"],
                metadata=r["payload"].get("metadata", {})
            ))
        return chunks

    def build_prompt(
        self,
        query: str,
        chunks: List[DocumentChunk],
        system_prompt: Optional[str] = None
    ) -> str:
        context = "\n\n".join([
            f"[Source {i+1} | Score: {c.score:.2f}]\n{c.content}"
            for i, c in enumerate(chunks)
        ])
        base_system = system_prompt or (
            "You are a helpful AI assistant. Answer questions based on the provided context. "
            "If the context doesn't contain enough information, say so clearly. "
            "Always cite your sources."
        )
        return {
            "system": base_system,
            "user": f"""Context:
{context}

---
Question: {query}

Answer based on the context above:"""
        }

    async def generate(
        self,
        prompt: dict,
        model: str,
        temperature: float,
        max_tokens: int
    ) -> tuple[str, int]:
        start = time.time()
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self.llm_url}/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": prompt["system"]},
                        {"role": "user", "content": prompt["user"]}
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens
                }
            )
            resp.raise_for_status()
            data = resp.json()

        latency = time.time() - start
        LLM_LATENCY.labels(model=model).observe(latency)

        answer = data["choices"][0]["message"]["content"]
        tokens = data.get("usage", {}).get("total_tokens", 0)

        TOKEN_COUNT.labels(type="prompt").inc(
            data.get("usage", {}).get("prompt_tokens", 0)
        )
        TOKEN_COUNT.labels(type="completion").inc(
            data.get("usage", {}).get("completion_tokens", 0)
        )
        return answer, tokens

    async def query(self, request: QueryRequest) -> QueryResponse:
        collection = request.collection or QDRANT_COLLECTION
        start = time.time()

        ACTIVE_QUERIES.inc()
        try:
            # Step 1: Embed query
            query_embedding = await self.get_embedding(request.query)

            # Step 2: Retrieve relevant chunks
            chunks = await self.retrieve(
                query_embedding, collection, request.top_k
            )
            if not chunks:
                logger.warning(f"No chunks retrieved for query: {request.query[:50]}")

            # Step 3: Build prompt
            prompt = self.build_prompt(request.query, chunks, request.system_prompt)

            # Step 4: Generate response
            answer, tokens = await self.generate(
                prompt, LLM_MODEL, request.temperature, request.max_tokens
            )

            total_ms = (time.time() - start) * 1000
            REQUEST_LATENCY.labels(endpoint="/query").observe(total_ms / 1000)

            return QueryResponse(
                query=request.query,
                answer=answer,
                retrieved_chunks=chunks,
                latency_ms=total_ms,
                model=LLM_MODEL,
                tokens_used=tokens,
                rag_mode=request.mode
            )
        finally:
            ACTIVE_QUERIES.dec()


# ─────────────────────────────────────────────
# App Lifecycle
# ─────────────────────────────────────────────
rag_engine = RAGEngine()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("RAG API starting up...")
    logger.info(f"Qdrant: {QDRANT_URL} | LLM: {LLM_BASE_URL} | Model: {LLM_MODEL}")
    yield
    logger.info("RAG API shutting down...")


# ─────────────────────────────────────────────
# FastAPI App
# ─────────────────────────────────────────────
app = FastAPI(
    title="GenAI RAG API",
    description="Production-grade RAG pipeline on AKS | esarath/genai-aks-poc",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for K8s readiness/liveness probes."""
    components = {}
    overall = "healthy"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{QDRANT_URL}/healthz")
            components["qdrant"] = "healthy" if r.status_code == 200 else "degraded"
    except Exception:
        components["qdrant"] = "unreachable"
        overall = "degraded"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{LLM_BASE_URL}/health")
            components["llm_gateway"] = "healthy" if r.status_code == 200 else "degraded"
    except Exception:
        components["llm_gateway"] = "unreachable"
        overall = "degraded"

    return HealthResponse(
        status=overall,
        version="1.0.0",
        components=components
    )


@app.post("/query", response_model=QueryResponse, tags=["RAG"])
async def query_rag(request: QueryRequest):
    """Execute a RAG query: embed → retrieve → generate."""
    REQUEST_COUNT.labels(method="POST", endpoint="/query", status="started").inc()
    try:
        response = await rag_engine.query(request)
        REQUEST_COUNT.labels(method="POST", endpoint="/query", status="success").inc()
        return response
    except httpx.TimeoutException:
        REQUEST_COUNT.labels(method="POST", endpoint="/query", status="timeout").inc()
        raise HTTPException(status_code=504, detail="LLM or retrieval timed out")
    except Exception as e:
        REQUEST_COUNT.labels(method="POST", endpoint="/query", status="error").inc()
        logger.error(f"RAG query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest", tags=["Data"])
async def ingest_documents(request: IngestRequest, background_tasks: BackgroundTasks):
    """Ingest documents: chunk → embed → store in Qdrant."""
    background_tasks.add_task(_ingest_task, request)
    return {"status": "accepted", "documents_queued": len(request.documents)}


async def _ingest_task(request: IngestRequest):
    """Background task for document ingestion."""
    collection = request.collection or QDRANT_COLLECTION
    logger.info(f"Ingesting {len(request.documents)} documents into {collection}")
    # Chunking + embedding logic would go here
    # For full implementation see: docs/ingestion-guide.md


@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Prometheus metrics endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/collections", tags=["Data"])
async def list_collections():
    """List all Qdrant collections."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(f"{QDRANT_URL}/collections")
        resp.raise_for_status()
        return resp.json()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
