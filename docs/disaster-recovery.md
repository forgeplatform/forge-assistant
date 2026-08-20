# Disaster Recovery — ChromaDB Index & Models

The assistant runs as two services, and each keeps its own persistent state:

| Deployment | API — vector index | Model server — model blobs |
|------------|--------------------|----------------------------|
| Docker Compose | volume `assistant_data` at `/data` | volume `ollama_models` at `/root/.ollama` |
| Kubernetes (forail-helm) | PVC `forail-assistant-data` (default **5Gi**) at `/data` | PVC `forail-assistant-ollama-models` (default **20Gi**) at `/root/.ollama` |

What each holds:

- **ChromaDB** (API) — the embedded vector store; collection `forail_docs`
  (configurable via `FORAIL_ASSISTANT_CHROMA_COLLECTION`). This is the
  RAG index built from your documentation.
- **Ollama models** (model server) — the pulled LLM (`gemma3:1b` by default)
  and the embedding model (`nomic-embed-text`).

Keeping them apart is the point: model blobs are far larger than the index and
outlive a rebuild of the API, so the index claim is sized by the corpus rather
than by the model.

## Key principle: the index is *rebuildable*, not precious

The ChromaDB index is **derived data** — it is generated from your source
documentation by the indexing pipeline. Losing it is a *fast, automatic*
recovery, not a data-loss event:

```bash
# Compose
curl -X POST "http://localhost:8100/api/v1/index?rebuild=true"

# Kubernetes
kubectl -n forail exec deploy/forail-assistant -- \
  curl -sX POST "http://localhost:8100/api/v1/index?rebuild=true"
```

Likewise, **Ollama models re-download automatically** if they are missing —
the API pulls them over Ollama's HTTP API when it starts. So the realistic
worst case — losing both volumes — recovers by: start the stack (models
re-pull) → re-index (index rebuilds). No restore from backup is strictly
required.

> This is why the assistant is safe to run with `assistant.enabled=false`
> by default and to add/remove freely: it carries no irreplaceable state.

## Recovery scenarios

| Scenario | Symptom | Recovery |
|----------|---------|----------|
| **Index empty / never built** | Chat answers with no doc context | `POST /api/v1/index` |
| **Index stale** (docs changed) | Answers cite old content | `POST /api/v1/index?rebuild=true` |
| **Index corrupted** | Chat errors, ChromaDB read failures in logs | Delete the Chroma dir under `/data`, restart, then `?rebuild=true` |
| **Models missing** | Health check fails on startup, "model not found" | Just restart the API — it re-pulls `gemma3:1b` + `nomic-embed-text` over Ollama's API |
| **Model server down / unreachable** | API exits after 300s with `Ollama not reachable at ...` | Check the `ollama` service (Compose) or the `forail-assistant-ollama` Deployment and its Service, then restart the API |
| **Total volume loss** | Fresh/empty volumes | Restart (models re-pull) → `POST /api/v1/index?rebuild=true` |
| **PVC lost (k8s)** | Pod stuck / volume gone | Recreate the PVC (helm re-apply); `forail-assistant-ollama-models` re-pulls, `forail-assistant-data` re-indexes |

## Optional: back up the volumes to skip re-download/re-index

Re-indexing and model re-download are usually faster than a restore, but
for air-gapped hosts (no registry to re-pull models from) or very large
corpora, back the volumes up. On an air-gapped host the **model** volume is
the one that matters — the index can always be rebuilt from `docs_to_index/`,
while models cannot be pulled at all:

```bash
# Compose — backup (index, then models)
docker run --rm -v forail-assistant_assistant_data:/data -v "$(pwd)/backups":/backup \
  alpine tar czf /backup/assistant-data.tar.gz /data
docker run --rm -v forail-assistant_ollama_models:/models -v "$(pwd)/backups":/backup \
  alpine tar czf /backup/ollama-models.tar.gz /models

# Compose — restore
docker run --rm -v forail-assistant_assistant_data:/data -v "$(pwd)/backups":/backup \
  alpine tar xzf /backup/assistant-data.tar.gz -C /
docker run --rm -v forail-assistant_ollama_models:/models -v "$(pwd)/backups":/backup \
  alpine tar xzf /backup/ollama-models.tar.gz -C /
```

```bash
# Kubernetes — snapshot both PVCs with your CSI VolumeSnapshot class, or copy them out:
kubectl -n forail exec deploy/forail-assistant -- tar czf - /data > assistant-data.tar.gz
kubectl -n forail exec deploy/forail-assistant-ollama -- tar czf - /root/.ollama > ollama-models.tar.gz
```

For air-gapped clusters, back both up **after** the first successful
model pull + index so the restore is fully self-contained.

## Recovery objectives

| | Target | Notes |
|---|--------|-------|
| **RPO** (index) | ~0 | Index is derived from source docs; rebuild reproduces it exactly. |
| **RTO** (index rebuild) | minutes | Scales with corpus size; `?rebuild=true` is idempotent. |
| **RTO** (model re-pull) | ~2 min | Network-dependent; ~1–2 GB for `gemma3:1b` + embeddings. |
| **RTO** (restore from backup) | minutes | Use when re-pull/re-index is impractical (air-gapped, huge corpus). |

## See also

- [deployment.md](deployment.md#backup-and-restore) — backup/restore commands and removal
- [ga-roadmap.md](ga-roadmap.md) — index lifecycle is a GA exit criterion
- [configuration.md](configuration.md) — `FORAIL_ASSISTANT_CHROMA_*` settings
