# Architecture

## Overview

Forail Assistant is a standalone microservice that provides AI-powered help for the Forail platform. It uses Retrieval-Augmented Generation (RAG) to answer questions based on indexed documentation.

```
                    ┌─────────────────────────────────┐
                    │         Forail Frontend           │
                    │  (React chat panel component)    │
                    └───────────────┬──────────────────┘
                                    │ SSE (Server-Sent Events)
                                    ▼
                    ┌─────────────────────────────────┐
                    │   Forail Assistant (API)          │
                    │                                  │
                    │  FastAPI  /api/v1/chat  → SSE    │
                    │           /api/v1/health→ JSON   │
                    │           /api/v1/index → reindex│
                    │                                  │
                    │  ChromaDB (embedded vector store) │
                    └───────────────┬──────────────────┘
                                    │ HTTP (internal network only)
                                    ▼
                    ┌─────────────────────────────────┐
                    │   Ollama (model server)           │
                    │                                  │
                    │  gemma3:1b        (generation)   │
                    │  nomic-embed-text (embeddings)   │
                    │                                  │
                    │  optional: NVIDIA GPU             │
                    └─────────────────────────────────┘
```

> **Note:** These are **two services**, not one container. The API image carries
> FastAPI and an embedded ChromaDB; Ollama runs beside it from its own pinned
> upstream image. In Compose that is the `ollama` service, in Kubernetes the
> `forail-assistant-ollama` Deployment. Only the model server needs a GPU or a
> large volume, so only it has to land on a GPU node.
>
> Ollama has no authentication. It is reachable on the internal network alone —
> no published port in Compose, and a ClusterIP Service in Kubernetes.

## Components

### FastAPI Application (`app/`)

The core service, responsible for:

- Receiving chat requests with optional page context and history
- Querying ChromaDB for relevant documentation chunks
- Building a context-enriched prompt for the LLM
- Streaming the response token-by-token via SSE

**Key files:**
- `app/main.py` — FastAPI app, endpoints, CORS
- `app/rag.py` — RAG pipeline (embed, retrieve, generate, stream)
- `app/indexer.py` — Document loading, chunking, indexing
- `app/config.py` — Pydantic settings from environment

### Ollama (Model Server)

Runs the language models locally, in its own container. Two models are used:
- **gemma3:1b** (default, or configured model) — for chat generation
- **nomic-embed-text** — for generating document/query embeddings

It runs from the official `ollama/ollama` image, **pinned** to an exact tag. It
used to be a single binary copied out of that image at build time, and that
broke silently: modern Ollama keeps its inference engine in `/usr/lib/ollama`
(`llama-server`, `libggml`, the CUDA backends), so the copied binary could start
a server and answer `/api/tags` — passing the health check — while every
generation returned HTTP 500. Running the upstream image whole, at a tag we
choose deliberately, is what closes that class of failure.

The API never shells out to the `ollama` CLI; it is not in the API image at all.
Models are pulled over Ollama's HTTP API on first start, and the API waits for
the model server before it accepts traffic (bounded at 300s, then it exits with
an actionable message rather than hanging).

GPU acceleration is optional and applies to this service alone — the
`docker-compose.gpu.yml` overlay in Compose, `assistant.ollama.gpu.enabled` in
the Helm chart. See the README for measured numbers.

### ChromaDB (Vector Store)

Stores document chunks as vectors for similarity search. When a user asks a question:
1. The question is embedded using `nomic-embed-text`
2. ChromaDB finds the top-K most similar document chunks
3. These chunks become the context for the LLM

## Data Flow

### Chat Request

```
1. User types "How do I create a scheduled job?"
2. Frontend sends POST /api/v1/chat with message + page context
3. Assistant embeds the question via Ollama /api/embeddings
4. Assistant queries ChromaDB for top 5 relevant doc chunks
5. Assistant builds system prompt with doc context
6. Assistant streams response from Ollama /api/chat
7. Each token is sent to frontend as SSE data event
8. Frontend renders tokens in real-time
```

### Document Indexing

```
1. Admin calls POST /api/v1/index (or runs indexer script)
2. Indexer reads all .md files from docs_to_index/
3. Each file is split into overlapping chunks (500 chars, 50 overlap)
4. Each chunk is embedded via Ollama nomic-embed-text
5. Embeddings + text stored in ChromaDB collection "forail_docs"
```

## Design Decisions

### Why Standalone Service (Not Django App)?

- **No Django dependency** — FastAPI is lighter, async-native, no ORM needed
- **Optional** — can be added/removed without touching core Forail
- **Independent scaling** — the model server is a separate service and can sit on its own GPU node
- **Independent release cycle** — update models without redeploying Forail

### Why Ollama (Not OpenAI/Claude API)?

- **Privacy** — all data stays on your infrastructure
- **Cost** — no API fees, no usage limits
- **Offline** — works without internet
- **Control** — choose and swap models freely

### Why FastAPI (Not Flask/Django)?

- **Native async** — SSE streaming without workarounds
- **Fast** — ASGI, built on Starlette
- **Auto docs** — OpenAPI schema generated automatically
- **Minimal** — no ORM, no admin, no migrations needed

### Why ChromaDB (Not Pinecone/Weaviate)?

- **Local** — no cloud dependency
- **Python-native** — simple API, no external clients
- **Lightweight** — single container, ~500MB
- **Good enough** — for <100K document chunks, ChromaDB performs well
