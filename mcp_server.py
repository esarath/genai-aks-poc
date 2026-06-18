"""
MCP Server: Claude ↔ AKS GenAI Pipeline Integration
Author: Sarath Babu | Senior DevOps + AI/MLOps Architect
GitHub: https://github.com/esarath/genai-aks-poc

This MCP server exposes AKS cluster operations and RAG pipeline
as tools that Claude can use via the Model Context Protocol.
"""

import os
import json
import asyncio
import logging
from typing import Any
import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
RAG_API_URL = os.getenv("RAG_API_URL", "http://rag-api:8000")
KUBECTL_PROXY_URL = os.getenv("KUBECTL_PROXY_URL", "http://localhost:8001")
NAMESPACE = os.getenv("K8S_NAMESPACE", "genai-rag")

# ─────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────
server = Server("genai-aks-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Expose all available tools to Claude."""
    return [
        # ── RAG Tools ──────────────────────────
        types.Tool(
            name="rag_query",
            description=(
                "Query the RAG pipeline with a natural language question. "
                "Retrieves relevant knowledge from the vector database and "
                "generates a grounded answer using the LLM."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The natural language question to answer"
                    },
                    "collection": {
                        "type": "string",
                        "description": "Qdrant collection name (default: genai-knowledge)",
                        "default": "genai-knowledge"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of chunks to retrieve",
                        "default": 5
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["naive", "advanced", "agentic"],
                        "description": "RAG mode to use",
                        "default": "naive"
                    }
                },
                "required": ["query"]
            }
        ),
        types.Tool(
            name="ingest_document",
            description="Ingest a text document into the RAG knowledge base.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Document text to ingest"
                    },
                    "collection": {
                        "type": "string",
                        "description": "Target Qdrant collection",
                        "default": "genai-knowledge"
                    },
                    "metadata": {
                        "type": "object",
                        "description": "Optional metadata (source, date, author)",
                        "default": {}
                    }
                },
                "required": ["content"]
            }
        ),
        # ── K8s Tools ──────────────────────────
        types.Tool(
            name="k8s_get_pods",
            description="List pods in the GenAI namespace with their status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "namespace": {
                        "type": "string",
                        "description": "Kubernetes namespace",
                        "default": "genai-rag"
                    },
                    "label_selector": {
                        "type": "string",
                        "description": "Label selector (e.g., app=rag-api)",
                        "default": ""
                    }
                }
            }
        ),
        types.Tool(
            name="k8s_get_logs",
            description="Retrieve logs from a pod or deployment.",
            inputSchema={
                "type": "object",
                "properties": {
                    "pod_name": {
                        "type": "string",
                        "description": "Pod name or deployment name"
                    },
                    "namespace": {
                        "type": "string",
                        "default": "genai-rag"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of log lines to return",
                        "default": 50
                    }
                },
                "required": ["pod_name"]
            }
        ),
        types.Tool(
            name="k8s_scale_deployment",
            description="Scale a deployment up or down.",
            inputSchema={
                "type": "object",
                "properties": {
                    "deployment": {
                        "type": "string",
                        "description": "Deployment name to scale"
                    },
                    "replicas": {
                        "type": "integer",
                        "description": "Target replica count",
                        "minimum": 0,
                        "maximum": 10
                    },
                    "namespace": {
                        "type": "string",
                        "default": "genai-rag"
                    }
                },
                "required": ["deployment", "replicas"]
            }
        ),
        # ── LLM Tools ──────────────────────────
        types.Tool(
            name="list_llm_models",
            description="List available LLM models in the gateway.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        types.Tool(
            name="get_rag_metrics",
            description="Get current Prometheus metrics for the RAG pipeline (latency, throughput, error rates).",
            inputSchema={
                "type": "object",
                "properties": {
                    "metric": {
                        "type": "string",
                        "description": "Specific metric name (optional, returns all if omitted)",
                        "default": ""
                    }
                }
            }
        ),
        types.Tool(
            name="list_collections",
            description="List all Qdrant vector database collections with document counts.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    """Handle tool calls from Claude."""

    try:
        if name == "rag_query":
            result = await _rag_query(arguments)

        elif name == "ingest_document":
            result = await _ingest_document(arguments)

        elif name == "k8s_get_pods":
            result = await _k8s_get_pods(arguments)

        elif name == "k8s_get_logs":
            result = await _k8s_get_logs(arguments)

        elif name == "k8s_scale_deployment":
            result = await _k8s_scale(arguments)

        elif name == "list_llm_models":
            result = await _list_models()

        elif name == "get_rag_metrics":
            result = await _get_metrics(arguments)

        elif name == "list_collections":
            result = await _list_collections()

        else:
            result = {"error": f"Unknown tool: {name}"}

        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    except Exception as e:
        logger.error(f"Tool '{name}' failed: {e}", exc_info=True)
        return [types.TextContent(
            type="text",
            text=json.dumps({"error": str(e), "tool": name})
        )]


# ─────────────────────────────────────────────
# Tool Implementations
# ─────────────────────────────────────────────

async def _rag_query(args: dict) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{RAG_API_URL}/query",
            json={
                "query": args["query"],
                "collection": args.get("collection", "genai-knowledge"),
                "top_k": args.get("top_k", 5),
                "mode": args.get("mode", "naive")
            }
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "answer": data["answer"],
            "sources_retrieved": len(data["retrieved_chunks"]),
            "latency_ms": round(data["latency_ms"], 2),
            "model": data["model"],
            "top_sources": [
                {"content": c["content"][:200], "score": c["score"]}
                for c in data["retrieved_chunks"][:3]
            ]
        }


async def _ingest_document(args: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{RAG_API_URL}/ingest",
            json={
                "documents": [args["content"]],
                "metadata": [args.get("metadata", {})],
                "collection": args.get("collection", "genai-knowledge")
            }
        )
        resp.raise_for_status()
        return {"status": "accepted", "message": "Document queued for ingestion"}


async def _k8s_get_pods(args: dict) -> dict:
    ns = args.get("namespace", NAMESPACE)
    label = args.get("label_selector", "")
    url = f"{KUBECTL_PROXY_URL}/api/v1/namespaces/{ns}/pods"
    if label:
        url += f"?labelSelector={label}"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        pods = resp.json()["items"]

    return {
        "namespace": ns,
        "pods": [
            {
                "name": p["metadata"]["name"],
                "status": p["status"]["phase"],
                "ready": all(
                    c["ready"] for c in p["status"].get("containerStatuses", [])
                ),
                "restarts": sum(
                    c.get("restartCount", 0)
                    for c in p["status"].get("containerStatuses", [])
                ),
                "node": p["spec"].get("nodeName", "unknown")
            }
            for p in pods
        ]
    }


async def _k8s_get_logs(args: dict) -> dict:
    ns = args.get("namespace", NAMESPACE)
    pod = args["pod_name"]
    lines = args.get("lines", 50)

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{KUBECTL_PROXY_URL}/api/v1/namespaces/{ns}/pods/{pod}/log",
            params={"tailLines": lines}
        )
        resp.raise_for_status()

    return {
        "pod": pod,
        "namespace": ns,
        "lines_returned": lines,
        "logs": resp.text
    }


async def _k8s_scale(args: dict) -> dict:
    ns = args.get("namespace", NAMESPACE)
    deployment = args["deployment"]
    replicas = args["replicas"]

    patch = {"spec": {"replicas": replicas}}
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.patch(
            f"{KUBECTL_PROXY_URL}/apis/apps/v1/namespaces/{ns}/deployments/{deployment}/scale",
            json=patch,
            headers={"Content-Type": "application/merge-patch+json"}
        )
        resp.raise_for_status()

    return {
        "deployment": deployment,
        "namespace": ns,
        "scaled_to": replicas,
        "status": "success"
    }


async def _list_models() -> dict:
    llm_url = os.getenv("LLM_BASE_URL", "http://llm-gateway:4000")
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{llm_url}/models")
        resp.raise_for_status()
        data = resp.json()
    return {"available_models": [m["id"] for m in data.get("data", [])]}


async def _get_metrics(args: dict) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{RAG_API_URL}/metrics")
        resp.raise_for_status()
    # Parse key metrics from Prometheus text format
    lines = resp.text.split("\n")
    metrics = {}
    for line in lines:
        if line and not line.startswith("#"):
            parts = line.split(" ")
            if len(parts) >= 2:
                metrics[parts[0]] = parts[1]
    return {"metrics": metrics}


async def _list_collections() -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{RAG_API_URL}/collections")
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────
async def main():
    logger.info("Starting GenAI AKS MCP Server...")
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
