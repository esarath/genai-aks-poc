# ── Multi-stage Dockerfile — RAG API (lightweight, non-root) ─────────────────
# Base: python:3.11-slim (~130MB vs full python:3.11 ~900MB)
# PRODUCTION: Use distroless or chainguard images for SBOM + CVE reduction

# Stage 1: dependency builder
FROM python:3.11-slim AS builder

WORKDIR /build
COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements.txt

# Pre-download embedding model so pod startup doesn't need internet
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('all-MiniLM-L6-v2')"

# Stage 2: runtime
FROM python:3.11-slim AS runtime

# Non-root user (UID 1000)
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

COPY --from=builder /install /usr/local
COPY --from=builder /root/.cache /home/appuser/.cache
COPY rag_api.py .

# Fix cache dir ownership
RUN chown -R appuser:appuser /app /home/appuser/.cache

USER 1000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "rag_api:app", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
