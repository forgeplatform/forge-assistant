#!/bin/bash
set -e

OLLAMA_URL="${FORAIL_ASSISTANT_OLLAMA_BASE_URL:-http://ollama:11434}"
LLM_MODEL="${FORAIL_ASSISTANT_OLLAMA_MODEL:-gemma3:1b}"
EMBED_MODEL="${FORAIL_ASSISTANT_OLLAMA_EMBED_MODEL:-nomic-embed-text}"

# Ollama runs in its own container now, so wait for it rather than starting it.
# Bounded: hanging here forever just turns a missing dependency into a pod that
# never reports anything useful.
echo "==> Waiting for Ollama at ${OLLAMA_URL}..."
for attempt in $(seq 1 150); do
    if curl -sf "${OLLAMA_URL}/" > /dev/null 2>&1; then
        echo "==> Ollama ready."
        break
    fi
    if [ "$attempt" -eq 150 ]; then
        echo "FATAL: Ollama not reachable at ${OLLAMA_URL} after 300s." >&2
        echo "       Check that the ollama service is running and that" >&2
        echo "       FORAIL_ASSISTANT_OLLAMA_BASE_URL points at it." >&2
        exit 1
    fi
    sleep 2
done

# The ollama CLI is no longer in this image, so models are pulled over the API.
ensure_model() {
    local model="$1"
    if curl -sf "${OLLAMA_URL}/api/tags" | grep -q "${model}"; then
        echo "==> Model ${model} already present."
        return
    fi
    echo "==> Pulling model ${model}..."
    curl -sf -X POST "${OLLAMA_URL}/api/pull" \
        -H 'Content-Type: application/json' \
        -d "{\"model\": \"${model}\"}" > /dev/null
    echo "==> Pulled ${model}."
}

ensure_model "${LLM_MODEL}"
ensure_model "${EMBED_MODEL}"

echo "==> Starting ChromaDB..."
# needtofix L13: ChromaDB binds 0.0.0.0 with no auth. This is safe only because
# it is confined to this pod/container and not exposed by a Service/port. Do NOT
# publish this port; if a shared instance is ever needed, put an authenticating
# proxy in front. The same applies to the Ollama service next door — it has no
# auth either, so it stays on the internal network with no published port.
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
