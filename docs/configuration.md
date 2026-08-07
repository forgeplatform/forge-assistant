# Configuration

All configuration is via environment variables with the `FORAIL_ASSISTANT_` prefix.

---

## Environment Variables

### Ollama Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `FORAIL_ASSISTANT_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API base URL. Ollama is a **separate service**, so this default only fits a hand-rolled setup with one on the host; the shipped image, the Compose file and the Helm chart all override it (`http://ollama:11434`, `http://forail-assistant-ollama:11434`) |
| `FORAIL_ASSISTANT_OLLAMA_MODEL` | `gemma3:1b` | LLM model for chat generation |
| `FORAIL_ASSISTANT_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Model for generating embeddings |
| `FORAIL_ASSISTANT_OLLAMA_TIMEOUT` | `120` | Timeout in seconds for Ollama requests |

### ChromaDB Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `FORAIL_ASSISTANT_CHROMA_HOST` | `localhost` | ChromaDB hostname (localhost — embedded in the same container) |
| `FORAIL_ASSISTANT_CHROMA_PORT` | `8000` | ChromaDB port |
| `FORAIL_ASSISTANT_CHROMA_COLLECTION` | `forail_docs` | Collection name for indexed documents |

### RAG Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `FORAIL_ASSISTANT_RAG_TOP_K` | `5` | Number of document chunks to retrieve per query |
| `FORAIL_ASSISTANT_RAG_CHUNK_SIZE` | `500` | Character count per document chunk |
| `FORAIL_ASSISTANT_RAG_CHUNK_OVERLAP` | `50` | Overlap between adjacent chunks |

### Application Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `FORAIL_ASSISTANT_APP_NAME` | `Forail Assistant` | Application display name |
| `FORAIL_ASSISTANT_APP_VERSION` | `2026.05.0` | Version string |
| `FORAIL_ASSISTANT_LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `FORAIL_ASSISTANT_CORS_ORIGINS` | `*` | Comma-separated list of allowed CORS origins |

---

## Model Selection

| Model | VRAM | Speed | Quality | Recommendation |
|-------|------|-------|---------|----------------|
| `tinyllama:1.1b` | 2 GB | Fastest | Basic | CPU-only, testing |
| `phi3:mini` | 4 GB | Fast | Good | CPU with 8+ GB RAM |
| `gemma3:1b` | 2 GB | Fast | Good | **Default** — works on CPU, good balance |
| `mistral:7b` | 6 GB | Medium | Excellent | GPU with 8+ GB VRAM |
| `llama3.1:8b` | 8 GB | Medium | Best | GPU with 10+ GB VRAM |

To change the model:
```bash
# Restart with the new model — the API pulls it over Ollama's HTTP API on
# start, so nothing has to be pulled by hand.
FORAIL_ASSISTANT_OLLAMA_MODEL=llama3.1:8b docker compose up -d
```

To pull one ahead of time, address the model server directly. The `ollama` CLI
is no longer in the API image — it is in the Ollama service:

```bash
docker compose exec ollama ollama pull llama3.1:8b
```

Anything above `gemma3:1b` wants the GPU overlay
(`-f docker-compose.gpu.yml`); the VRAM column above is the model server's
requirement alone, since it is the only service doing inference.

---

## Document Sources

Place markdown files in `docs_to_index/` to make them searchable:

```
docs_to_index/
├── api_reference/     # API endpoint documentation
│   ├── jobs.md
│   ├── templates.md
│   └── inventories.md
├── user_guide/        # User instructions
│   ├── getting_started.md
│   ├── schedules.md
│   └── workflows.md
└── errors/            # Known errors and solutions
    └── common_errors.md
```

After adding files, trigger re-indexing:
```bash
curl -X POST http://localhost:8100/api/v1/index?rebuild=true
```
