"""RAG pipeline: ChromaDB retrieval + Ollama generation."""

import json
import logging
from typing import AsyncGenerator

import httpx

from app.config import settings
from app.db import get_chroma_collection, get_embedding

logger = logging.getLogger(__name__)


async def retrieve_context(query: str, top_k: int = None) -> list[str]:
    """Retrieve relevant document chunks from ChromaDB."""
    if top_k is None:
        top_k = settings.rag_top_k

    try:
        collection = get_chroma_collection()
        embedding = await get_embedding(query)
        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
        )
        if results and results["documents"]:
            return results["documents"][0]
    except Exception:
        logger.exception("Failed to retrieve context from ChromaDB")

    return []


def build_system_prompt(context_docs: list[str], page_context: str = "") -> str:
    """Build the system prompt with RAG context."""
    docs_text = "\n\n---\n\n".join(context_docs) if context_docs else "No documentation context available."

    prompt = f"""You are Forail Assistant, an AI helper for the Forail infrastructure automation platform.

Answer questions using the following documentation context. If the documentation does not contain the answer, say so honestly — do not make things up.

Be concise and practical. Give step-by-step instructions when helpful.
Use markdown formatting for code blocks, lists, and emphasis.

Documentation context:
{docs_text}"""

    if page_context:
        prompt += f"\n\nThe user is currently on page: {page_context}"

    return prompt


async def stream_chat(
    message: str,
    page_context: str = "",
    history: list[dict] | None = None,
) -> AsyncGenerator[str, None]:
    """
    Stream a chat response from Ollama with RAG context.

    Yields individual tokens as they arrive.
    """
    # 1. Retrieve relevant docs
    context_docs = await retrieve_context(message)

    # 2. Build messages
    system_prompt = build_system_prompt(context_docs, page_context)
    messages = [{"role": "system", "content": system_prompt}]

    if history:
        for entry in history[-6:]:  # Last 3 exchanges
            # needtofix L11: the role is client-controlled. Only accept
            # user/assistant turns — a caller must not be able to inject a
            # 'system' message (prompt injection) or crash us with a malformed
            # entry missing role/content.
            if not isinstance(entry, dict):
                continue
            role = entry.get("role")
            content = entry.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str):
                continue
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": message})

    # 3. Stream from Ollama
    timeout = httpx.Timeout(connect=10.0, read=settings.ollama_timeout, write=10.0, pool=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "messages": messages,
                "stream": True,
            },
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if not data.get("done") and "message" in data:
                        token = data["message"].get("content", "")
                        if token:
                            yield token
                except json.JSONDecodeError:
                    continue


async def check_ollama_health() -> bool:
    """Check if Ollama is reachable and has the required model."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
            return settings.ollama_model in models
    except Exception:
        return False


async def check_chroma_health() -> bool:
    """Check if ChromaDB is reachable."""
    try:
        collection = get_chroma_collection()
        collection.count()
        return True
    except Exception:
        return False
