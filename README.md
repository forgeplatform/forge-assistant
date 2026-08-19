# Forail Assistant

[![CI](https://github.com/forail-platform/forail-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/forail-platform/forail-assistant/actions/workflows/ci.yml)

> ⚠️ **Status: Under active development — not yet production-ready.**
> The AI assistant is shipped as a **preview** to gather early feedback. APIs, models, default prompts, and capabilities may change between releases. Do not depend on it for critical workflows.
> The path out of preview and the criteria for General Availability are tracked in the [GA Roadmap](docs/ga-roadmap.md); operational recovery is covered in [Disaster Recovery](docs/disaster-recovery.md).

AI-powered assistant for the Forail infrastructure automation platform. Uses a local Ollama LLM with RAG (Retrieval-Augmented Generation) to provide contextual help, error analysis, and documentation search.

## Overview

Forail Assistant is an **optional, standalone service** that can be plugged into or removed from any Forail deployment. It runs as **two containers**: the API (FastAPI + embedded ChromaDB) and Ollama, the model server.

```
┌──────────────────┐     ┌───────────────────────────────┐     ┌──────────────┐
│  Forail Frontend  │────▶│      Forail Assistant API      │────▶│    Ollama     │
│  (React chat)    │ SSE │  ┌──────────────────────────┐ │HTTP │  gemma3:1b    │
└──────────────────┘     │  │  FastAPI (RAG pipeline)   │ │     │  (GPU here)   │
                         │  └────────────┬─────────────┘ │     └──────────────┘
                         │  ┌────────────▼─────────────┐ │
                         │  │    ChromaDB (embedded)    │ │
                         │  └──────────────────────────┘ │
                         └───────────────────────────────┘
```

They are separate on purpose: only the model server benefits from a GPU, so
only it carries the GPU requirement. In Kubernetes that means just one pod has
to land on a GPU node while the API stays schedulable anywhere. Ollama has no
authentication, so it is never given a published port — only the API talks to it.

## Features

- **Contextual help** — knows which page the user is on
- **Documentation search** — RAG-powered answers from indexed Forail/Ansible docs
- **Error explanation** — analyze failed job output
- **Streaming responses** — token-by-token display via Server-Sent Events
- **Privacy-first** — all data stays on your server, no cloud APIs

## Quick Start

```bash
# Start the assistant (API + Ollama)
docker compose up -d

# ...or with GPU acceleration for the model server (see Hardware below)
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d

# Wait ~2 minutes for Ollama to load the model on first start,
# then index documentation
curl -X POST http://localhost:8100/api/v1/index

# Test it
curl -X POST http://localhost:8100/api/v1/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "How do I create a job template?"}'
```

> **Note:** On first start, the API waits for Ollama and then pulls the LLM model (`gemma3:1b`) and embedding model (`nomic-embed-text`) over Ollama's API. The healthcheck `start_period` is 120 seconds to allow time for this.

## Integration with Forail

To add the assistant to an existing Forail deployment:

```bash
cd /opt/forail
docker compose -f docker-compose.yml -f path/to/forail-assistant/docker-compose.integration.yml up -d
```

The frontend automatically detects the assistant via health check and shows the chat button.

## Configuration

All settings via environment variables with `FORAIL_ASSISTANT_` prefix:

| Variable | Default | Description |
|----------|---------|-------------|
| `FORAIL_ASSISTANT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL. The code defaults to localhost for local development; the image and the Helm chart both override it to point at the Ollama service |
| `FORAIL_ASSISTANT_OLLAMA_MODEL` | `gemma3:1b` | LLM model |
| `FORAIL_ASSISTANT_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `FORAIL_ASSISTANT_CHROMA_HOST` | `localhost` | ChromaDB host (localhost — embedded in the API container) |
| `FORAIL_ASSISTANT_CHROMA_PORT` | `8000` | ChromaDB port |
| `FORAIL_ASSISTANT_RAG_TOP_K` | `3` | Number of docs to retrieve |
| `FORAIL_ASSISTANT_LOG_LEVEL` | `INFO` | Logging level |

## Hardware Requirements

The GPU overlay needs the NVIDIA driver plus `nvidia-container-toolkit`
registered with Docker (`nvidia-ctk runtime configure --runtime=docker`).
Without it the reservation fails and the stack refuses to start — deliberately,
so that a missing GPU is loud rather than a silent fall back to CPU.

Ollama picks CPU silently when it cannot see a device. Always confirm:

```bash
docker compose logs ollama | grep "inference compute"
# GPU:  library=CUDA ... description="NVIDIA GeForce RTX 3080" total="11.6 GiB"
# CPU:  library=cpu ... name=cpu
```

Measured on a Ryzen 9 5900X / RTX 3080 12GB, `gemma3:1b`, warm (model already
resident), same two questions against the same index:

| Setup | Time to first token | Generation throughput |
|-------|--------------------|----------------------|
| CPU (24 threads) | ~0.5s | ~680 B/s |
| GPU (RTX 3080) | ~0.5s | ~3900 B/s |

Time to first token is dominated by RAG retrieval, so it barely moves; the GPU
buys roughly **5–6× generation throughput**. That matters most as a headroom
budget: it is what makes a larger, more accurate model affordable at all, since
an 8B-class model on CPU is slower again by a wide margin.

## Development

```bash
# Install dependencies
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

# Run tests
pytest tests/ -v

# Lint
ruff check app/ tests/

# Run dev server
uvicorn app.main:app --reload --port 8100
```

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/health` | GET | Health check (Ollama + ChromaDB status) |
| `/api/v1/chat` | POST | Chat with SSE streaming |
| `/api/v1/index` | POST | Trigger document re-indexing |
| `/api/v1/docs` | GET | OpenAPI documentation |

## Documentation

- [Architecture](docs/architecture.md)
- [API Reference](docs/api-reference.md)
- [Configuration](docs/configuration.md)
- [Deployment](docs/deployment.md)
- [GA Roadmap](docs/ga-roadmap.md) — preview → GA exit criteria and milestones
- [Disaster Recovery](docs/disaster-recovery.md) — ChromaDB index backup, restore, and rebuild

## License

Part of the [Forail Platform](https://github.com/forail-platform).
