"""
Agentic AI Workflow - LangChain ReAct Agent
Author: Sarath Babu | Senior DevOps + AI/MLOps Architect
GitHub: https://github.com/esarath/genai-aks-poc

Demonstrates a ReAct agent with RAG, web search, and K8s tools.
"""

import os
import logging
from typing import TypedDict, Annotated, Sequence
import operator

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
import httpx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://llm-gateway:4000")
RAG_API_URL = os.getenv("RAG_API_URL", "http://rag-api:8000")
LLM_MODEL = os.getenv("LLM_MODEL", "phi3:mini")

# ─────────────────────────────────────────────
# Agent State
# ─────────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    iteration: int
    context: dict


# ─────────────────────────────────────────────
# Agent Tools
# ─────────────────────────────────────────────
@tool
async def rag_search(query: str, collection: str = "genai-knowledge") -> str:
    """
    Search the RAG knowledge base for information relevant to the query.
    Use this when you need factual information from the knowledge base.
    
    Args:
        query: Natural language search query
        collection: Qdrant collection to search
    
    Returns:
        Retrieved information with source scores
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{RAG_API_URL}/query",
            json={"query": query, "collection": collection, "top_k": 3}
        )
        resp.raise_for_status()
        data = resp.json()
    
    sources = "\n".join([
        f"[{i+1}] {c['content'][:300]} (score: {c['score']:.2f})"
        for i, c in enumerate(data["retrieved_chunks"])
    ])
    return f"Answer: {data['answer']}\n\nSources:\n{sources}"


@tool
async def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression safely.
    
    Args:
        expression: Mathematical expression to evaluate (e.g., "2 + 2 * 10")
    
    Returns:
        Calculation result
    """
    try:
        # Safe eval with limited builtins
        allowed = {"__builtins__": {}, "abs": abs, "round": round, "min": min, "max": max}
        result = eval(expression, allowed)
        return f"Result: {result}"
    except Exception as e:
        return f"Calculation error: {e}"


@tool
async def check_cluster_health() -> str:
    """
    Check the health status of the GenAI AKS cluster components.
    Use this when asked about system status or infrastructure health.
    
    Returns:
        Health status of all GenAI components
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{RAG_API_URL}/health")
        resp.raise_for_status()
        data = resp.json()
    
    return f"Cluster Health: {data['status']}\nComponents: {data['components']}"


@tool
async def list_knowledge_bases() -> str:
    """
    List all available knowledge base collections in the vector database.
    
    Returns:
        List of Qdrant collections with metadata
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{RAG_API_URL}/collections")
        resp.raise_for_status()
        data = resp.json()
    return f"Available collections: {data}"


@tool
def format_report(title: str, sections: list[str]) -> str:
    """
    Format a structured report from provided sections.
    
    Args:
        title: Report title
        sections: List of section texts
    
    Returns:
        Formatted markdown report
    """
    report = f"# {title}\n\n"
    for i, section in enumerate(sections, 1):
        report += f"## Section {i}\n{section}\n\n"
    return report


# ─────────────────────────────────────────────
# Agent Graph
# ─────────────────────────────────────────────
TOOLS = [rag_search, calculate, check_cluster_health, list_knowledge_bases, format_report]

def create_agent(system_prompt: str = None):
    """Create a LangGraph ReAct agent with GenAI tools."""
    
    # LLM via LiteLLM gateway (Ollama/Azure OpenAI)
    llm = ChatOpenAI(
        model=LLM_MODEL,
        base_url=f"{LLM_BASE_URL}/v1",
        api_key="not-needed",  # LiteLLM handles auth
        temperature=0.1,
        max_tokens=2048
    )
    
    llm_with_tools = llm.bind_tools(TOOLS)
    
    default_system = (
        "You are an expert AI/MLOps assistant with access to a GenAI knowledge base "
        "running on Azure AKS. You can search knowledge, check cluster health, and "
        "perform calculations. Always use tools to get accurate information before answering. "
        "Think step by step and use multiple tools if needed."
    )
    
    sys_prompt = system_prompt or default_system
    
    def agent_node(state: AgentState) -> dict:
        """Main reasoning node."""
        messages = state["messages"]
        iteration = state.get("iteration", 0)
        
        if iteration > 10:
            return {
                "messages": [AIMessage(content="Max iterations reached. Here's what I found so far.")],
                "iteration": iteration
            }
        
        # Prepend system message
        from langchain_core.messages import SystemMessage
        full_messages = [SystemMessage(content=sys_prompt)] + list(messages)
        
        response = llm_with_tools.invoke(full_messages)
        return {
            "messages": [response],
            "iteration": iteration + 1
        }
    
    def should_continue(state: AgentState) -> str:
        """Decide: continue with tools or end."""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return END
    
    # Build graph
    workflow = StateGraph(AgentState)
    
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(TOOLS))
    
    workflow.set_entry_point("agent")
    
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {"tools": "tools", END: END}
    )
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()


# ─────────────────────────────────────────────
# Usage Example
# ─────────────────────────────────────────────
async def run_agent_example():
    """Demonstrate agentic workflow."""
    agent = create_agent()
    
    queries = [
        "What is RAG (Retrieval Augmented Generation) and how is it implemented in our AKS cluster?",
        "Check the health of our GenAI cluster and list all available knowledge bases.",
        "Search the knowledge base for Kubernetes autoscaling best practices and summarize them.",
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print('='*60)
        
        result = await agent.ainvoke({
            "messages": [HumanMessage(content=query)],
            "iteration": 0,
            "context": {}
        })
        
        final_message = result["messages"][-1]
        print(f"Answer:\n{final_message.content}")
        print(f"Iterations: {result['iteration']}")


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_agent_example())
