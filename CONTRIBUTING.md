# Contributing to forail-assistant

Thanks for your interest in contributing!

The full contributing guide — git workflow, commit conventions, coding standards, PR process — lives in the [Forail developer docs](https://forail-platform.github.io/dev/contributing.html). Please read it before submitting a pull request.

## What lives here

FastAPI-based AI assistant service for the Forail platform. Ships as an all-in-one container image bundling Ollama (LLM runtime) and ChromaDB (vector store), with `gemma3:1b` as the default model.

## Quick start

```bash
git clone https://github.com/forail-platform/forail-assistant.git
cd forail-assistant
make develop          # build + run local container
curl http://localhost:8001/health
```

See [README.md](./README.md) for full setup.

## Assistant-specific guidelines

- **All-in-one image** — Ollama + ChromaDB are baked into the image (`Dockerfile`). The `entrypoint.sh` boots Ollama, pulls the model if missing, and starts FastAPI. Do not split these without an architecture discussion first.
- **Model defaults** — `gemma3:1b` is the bundled default (small enough to run on a 2 GB pod). Larger models can be configured via env vars but are not bundled.
- **Tests** — `make test` runs the suite (29+ tests as of v2026.05.0). New endpoints need tests.
- **CHANGELOG** — every version bump needs a [CHANGELOG.md](./CHANGELOG.md) entry.

## Reporting bugs

Open an issue with reproduction steps, assistant version, model used, and any relevant log output.

For security vulnerabilities, see [SECURITY.md](./SECURITY.md) — please do **not** open a public issue.
