"""Forail Assistant — FastAPI application."""

import asyncio
import hmac
import json
import logging
import time

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.rag import stream_chat, check_ollama_health, check_chroma_health

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

# needtofix M13: never combine a wildcard origin with credentials — Starlette
# would reflect any Origin and return Access-Control-Allow-Credentials: true,
# letting any site make credentialed cross-origin requests. Only allow
# credentials when the origins are an explicit allow-list.
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_wildcard_cors = "*" in _cors_origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not _wildcard_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)

# needtofix M14: bound concurrent LLM generations to avoid GPU/CPU exhaustion.
_chat_semaphore = asyncio.Semaphore(max(1, settings.chat_max_concurrency))


@app.on_event("startup")
async def _warn_open_chat():
    if not settings.chat_token:
        logger.warning(
            "chat endpoint is UNAUTHENTICATED — set FORAIL_ASSISTANT_CHAT_TOKEN "
            "to require a bearer token (needtofix M14)."
        )
    if _wildcard_cors:
        logger.warning("CORS is a wildcard; credentials are disabled (needtofix M13).")


def _require_chat_auth(authorization: str | None):
    """Enforce the shared chat bearer token when configured (constant-time)."""
    if not settings.chat_token:
        return  # open mode (logged at startup)
    expected = f"Bearer {settings.chat_token}"
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


# --- Models ---

class ChatRequest(BaseModel):
    message: str
    context: dict | None = None
    history: list[dict] | None = None


def _bounded_request(req: "ChatRequest") -> tuple[str, list[dict]]:
    """
    The message and history this request is allowed to spend, or 413.

    The concurrency cap limits how many generations run at once and says nothing
    about how large any one of them is: four callers could hold every slot for
    the full Ollama timeout with a prompt the size of a book. History matters
    more than the message, because every turn is re-sent to the model and paid
    for again on the next request.
    """
    message = (req.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message must not be empty")
    if len(message) > settings.chat_max_message_chars:
        raise HTTPException(
            status_code=413,
            detail=f"message must be at most {settings.chat_max_message_chars} characters",
        )

    history = req.history or []
    if not isinstance(history, list):
        raise HTTPException(status_code=400, detail="history must be a list")

    # Trimmed rather than rejected: dropping the oldest turns degrades the answer
    # a little, while a 413 in the middle of a conversation ends it.
    history = history[-settings.chat_max_history_turns:]
    budget = settings.chat_max_history_chars
    kept: list[dict] = []
    for turn in reversed(history):
        if not isinstance(turn, dict):
            continue
        cost = len(str(turn.get("content", "")))
        if cost > budget:
            break
        budget -= cost
        kept.append(turn)
    kept.reverse()
    return message, kept


class HealthResponse(BaseModel):
    status: str
    version: str
    ollama: bool
    chromadb: bool
    model: str


# --- Endpoints ---

@app.get("/api/v1/health", response_model=HealthResponse)
async def health():
    """Health check — reports status of Ollama and ChromaDB dependencies."""
    ollama_ok = await check_ollama_health()
    chroma_ok = await check_chroma_health()

    return HealthResponse(
        status="ok" if (ollama_ok and chroma_ok) else "degraded",
        version=settings.app_version,
        ollama=ollama_ok,
        chromadb=chroma_ok,
        model=settings.ollama_model,
    )


@app.post("/api/v1/chat")
async def chat(req: ChatRequest, authorization: str | None = Header(default=None)):
    """
    Chat endpoint with SSE streaming response.

    Request body:
    ```json
    {
        "message": "How do I create a job template?",
        "context": {"page": "/templates"},
        "history": [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"}
        ]
    }
    ```

    Response: Server-Sent Events stream
    ```
    data: {"token": "To"}
    data: {"token": " create"}
    data: {"token": " a"}
    ...
    data: {"done": true}
    ```
    """
    _require_chat_auth(authorization)

    # Reject a flood before starting an expensive generation (M14).
    if _chat_semaphore.locked():
        raise HTTPException(status_code=429, detail="Assistant busy, retry shortly")

    message, history = _bounded_request(req)

    page_context = ""
    if req.context and req.context.get("page"):
        page_context = str(req.context["page"])[:200]

    async def event_generator():
        async with _chat_semaphore:
            deadline = time.monotonic() + settings.chat_deadline_seconds
            try:
                async for token in stream_chat(
                    message=message,
                    page_context=page_context,
                    history=history,
                ):
                    # A generation that will not stop still has to end: the
                    # slot it holds is one of only chat_max_concurrency.
                    if time.monotonic() > deadline:
                        logger.warning(
                            "Chat generation exceeded %ss deadline; cutting the stream",
                            settings.chat_deadline_seconds,
                        )
                        yield {"data": json.dumps({"error": "response timed out", "done": True})}
                        return
                    yield {"data": json.dumps({"token": token})}
                yield {"data": json.dumps({"done": True})}
            except Exception:
                # needtofix L12: never stream internal exception text to clients.
                logger.exception("Error during chat streaming")
                yield {"data": json.dumps({"error": "internal error", "done": True})}

    return EventSourceResponse(event_generator())


@app.post("/api/v1/index")
async def trigger_index(
    rebuild: bool = False,
    x_admin_token: str | None = Header(default=None),
):
    """
    Trigger document re-indexing. Protected by FORAIL_ASSISTANT_ADMIN_TOKEN.

    When no admin token is configured the endpoint is disabled (503).
    When configured, callers must send a matching `X-Admin-Token` header.
    """
    if not settings.admin_token:
        raise HTTPException(
            status_code=503,
            detail="Indexing endpoint disabled: set FORAIL_ASSISTANT_ADMIN_TOKEN",
        )
    # needtofix L10: constant-time compare to avoid a timing side-channel.
    if not x_admin_token or not hmac.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Token")

    from app.indexer import index_documents
    count = index_documents(rebuild=rebuild)
    return {"indexed_chunks": count, "rebuild": rebuild}
