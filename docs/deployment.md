# Deployment

## Standalone Deployment

Run the assistant independently:

```bash
cd forail-assistant
docker compose up -d
```

This starts **two containers**:

| Service | Contains | Ports |
|---------|----------|-------|
| `forail-assistant` | FastAPI API server + embedded ChromaDB (port 8000, in-container) | 8100 published |
| `ollama` | The model server, from the pinned `ollama/ollama` image | none published |

Ollama is deliberately given no published port: it has no authentication, so it
is reachable only by the API over the Compose network. Each service keeps its
own volume — `assistant_data` for the vector index, `ollama_models` for model
blobs — so rebuilding one does not discard the other's data.

### First-Time Setup

On first start the API waits for the model server to come up, then pulls the LLM
model (`gemma3:1b`) and the embedding model (`nomic-embed-text`) over Ollama's
HTTP API. Allow ~2 minutes for the initial download. The wait is bounded at
300s; past that the API exits with the URL it was trying to reach rather than
hanging.

```bash
# 1. Start both services
docker compose up -d

# 2. Wait for health check to pass (start_period is 120s)
docker compose logs -f forail-assistant

# 3. Index documentation
curl -X POST http://localhost:8100/api/v1/index

# 4. Verify
curl http://localhost:8100/api/v1/health
```

---

## Integration with Forail Platform

### Step 1: Add to Docker Compose

In your `forail-deploy` directory:

```bash
docker compose -f docker-compose.yml \
  -f /path/to/forail-assistant/docker-compose.integration.yml \
  up -d
```

### Step 2: Configure Nginx

Add to your Forail nginx configuration:

```nginx
# In forail-deploy/nginx/nginx.conf, inside the server block:
location /assistant/ {
    proxy_pass http://forail-assistant:8100/;
    proxy_http_version 1.1;
    proxy_set_header Connection '';
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    # SSE support
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 300s;
}
```

### Step 3: Frontend Detection

The Forail frontend automatically detects the assistant by calling `/assistant/api/v1/health`. If the endpoint responds, the chat button appears in the UI.

---

## GPU Support

Inference happens in the `ollama` service alone, so that is the only service the
GPU is handed to. It ships as an overlay rather than a commented-out block:

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d
```

The reservation is a hard requirement, on purpose — on a host without a usable
GPU the stack refuses to start instead of quietly falling back to CPU.

Requirements:
- NVIDIA GPU (8+ GB VRAM for an 8B-class model; `gemma3:1b` needs ~2 GB)
- `nvidia-container-toolkit` installed and registered with Docker:
  `sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`

Ollama falls back to CPU silently when it cannot see a device, so confirm:

```bash
docker compose logs ollama | grep "inference compute"
# must report library=CUDA and non-zero VRAM, not library=cpu
```

---

## CPU-Only Deployment

For servers without GPU, use a smaller model:

```bash
FORAIL_ASSISTANT_OLLAMA_MODEL=phi3:mini docker compose up -d
```

Response time will be 10-20 seconds instead of 2-5 seconds.

---

## Removing the Assistant

To remove the assistant from a running Forail deployment:

```bash
# Stop the assistant services (both of them — stopping only the API leaves
# the model server running and holding its volume)
docker compose -f docker-compose.yml \
  -f /path/to/forail-assistant/docker-compose.integration.yml \
  down forail-assistant ollama

# Or if running standalone
cd forail-assistant && docker compose down -v
```

The Forail platform continues to work normally. The chat button disappears automatically when the health check fails.

---

## Backup and Restore

Persistent data lives in two volumes, one per service:

| Volume | Mounted at | Holds |
|--------|-----------|-------|
| `assistant_data` | `/data` in the API container | the ChromaDB vector index |
| `ollama_models` | `/root/.ollama` in the model server | pulled model blobs |

```bash
# Backup the vector index
docker run --rm -v forail-assistant_assistant_data:/data -v $(pwd)/backups:/backup \
  alpine tar czf /backup/assistant-data.tar.gz /data

# Restore
docker run --rm -v forail-assistant_assistant_data:/data -v $(pwd)/backups:/backup \
  alpine tar xzf /backup/assistant-data.tar.gz -C /
```

> **Tip:** Neither volume actually has to be backed up. Re-indexing
> (`curl -X POST http://localhost:8100/api/v1/index?rebuild=true`) rebuilds the
> index from `docs_to_index/`, and models re-download on first start when
> `ollama_models` is empty. Back `ollama_models` up only to avoid re-pulling
> several GB on a metered or air-gapped host.

---

## CI/CD Pipeline

The repository ships with a **GitHub Actions** workflow in `.github/workflows/ci.yml`:

1. **Lint** — ruff check on Python code
2. **Test** — pytest with JUnit XML reporting
3. **Build** — Docker image build
4. **Scan** — Trivy container vulnerability scan
5. **Push** — Push to `ghcr.io/forail-platform/forail-assistant` (main branch and version tags only)

Tests must pass before any image is built or pushed. Releases use the built-in `GITHUB_TOKEN` with `packages: write` — no external secrets required.
