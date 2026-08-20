"""Tests for configuration module."""

import os

from app.config import Settings


def test_default_settings(monkeypatch):
    # The shipped image sets FORAIL_ASSISTANT_* variables (it points the API at
    # the ollama service, not localhost), so without clearing them this asserts
    # the environment rather than the code's defaults — and fails when run
    # inside that image.
    for name in list(os.environ):
        if name.startswith("FORAIL_ASSISTANT_"):
            monkeypatch.delenv(name)

    s = Settings()
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.ollama_model == "gemma3:1b"
    assert s.ollama_embed_model == "nomic-embed-text"
    assert s.chroma_host == "localhost"
    assert s.chroma_port == 8000
    assert s.chroma_collection == "forail_docs"
    assert s.rag_top_k == 3
    assert s.rag_chunk_size == 500
    assert s.rag_chunk_overlap == 50


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("FORAIL_ASSISTANT_OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setenv("FORAIL_ASSISTANT_CHROMA_PORT", "9000")
    monkeypatch.setenv("FORAIL_ASSISTANT_RAG_TOP_K", "10")

    s = Settings()
    assert s.ollama_model == "llama3.1:8b"
    assert s.chroma_port == 9000
    assert s.rag_top_k == 10
