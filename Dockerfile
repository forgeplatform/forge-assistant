### Forail Assistant — API image
### FastAPI (RAG pipeline) + ChromaDB (embedded).
###
### Ollama is NOT bundled here. It runs as its own service so that only the
### model server needs a GPU (and, in Kubernetes, only that pod needs to land
### on a GPU node). See docker-compose.yml, or the forail-assistant-ollama
### Deployment in the Helm chart.
###
### The previous all-in-one layout copied /bin/ollama out of the official
### image on its own. That silently stopped working: modern Ollama keeps the
### inference engine in /usr/lib/ollama (llama-server, libggml, the CUDA
### backends), so the copied binary could start a server but never load a
### model — every request came back 500.

FROM python:3.12-slim

# System deps for ChromaDB (sqlite3, build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY app/ ./app/
COPY docs_to_index/ ./docs_to_index/

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Directory for the ChromaDB index. Model blobs live in the Ollama service's
# own volume, not here.
RUN mkdir -p /data/chroma

# Default points at the Ollama service by its compose/Service name. Both the
# compose file and the Helm chart set this explicitly; the default only keeps
# a bare `docker run` on the same network working.
ENV FORAIL_ASSISTANT_OLLAMA_BASE_URL=http://ollama:11434
ENV FORAIL_ASSISTANT_OLLAMA_MODEL=gemma3:1b
ENV FORAIL_ASSISTANT_CHROMA_HOST=localhost
ENV FORAIL_ASSISTANT_CHROMA_PORT=8000
ENV FORAIL_ASSISTANT_LOG_LEVEL=INFO

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -sf http://localhost:8100/api/v1/health || exit 1

ENTRYPOINT ["/entrypoint.sh"]
