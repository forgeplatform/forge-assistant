#!/bin/bash
set -e

echo "==> Starting Ollama server..."
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "==> Waiting for Ollama..."
until curl -sf http://localhost:11434/ > /dev/null 2>&1; do
    sleep 1
done
echo "==> Ollama ready."

# Pull models if not present
if ! ollama list 2>/dev/null | grep -q "${FORAIL_ASSISTANT_OLLAMA_MODEL:-gemma3:1b}"; then
    echo "==> Pulling model ${FORAIL_ASSISTANT_OLLAMA_MODEL:-gemma3:1b}..."
    ollama pull "${FORAIL_ASSISTANT_OLLAMA_MODEL:-gemma3:1b}"
fi

if ! ollama list 2>/dev/null | grep -q "nomic-embed-text"; then
    echo "==> Pulling embedding model nomic-embed-text..."
    ollama pull nomic-embed-text
fi

echo "==> Starting ChromaDB..."
# needtofix L13: ChromaDB (and Ollama) bind 0.0.0.0 with no auth. This is safe
# only because they are confined to this pod/container and not exposed by a
# Service/port. Do NOT publish these ports; if a shared instance is ever
# needed, put an authenticating proxy in front.
chroma run --host 0.0.0.0 --port 8000 --path /data/chroma > /dev/null 2>&1 &
CHROMA_PID=$!

# Wait for ChromaDB
echo "==> Waiting for ChromaDB..."
until curl -sf http://localhost:8000/api/v2/heartbeat > /dev/null 2>&1; do
    sleep 1
done
echo "==> ChromaDB ready."

# Index documents on first start
echo "==> Indexing documentation..."
cd /app && python -c "from app.indexer import index_documents; count = index_documents(); print(f'Indexed {count} chunks')"

echo "==> Starting Forail Assistant API..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8100
