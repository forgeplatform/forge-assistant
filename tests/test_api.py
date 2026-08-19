"""Tests for FastAPI endpoints."""

import json
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestHealthEndpoint:

    def test_health_ok(self, client):
        with patch("app.main.check_ollama_health", new_callable=AsyncMock, return_value=True), \
             patch("app.main.check_chroma_health", new_callable=AsyncMock, return_value=True):
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["ollama"] is True
            assert data["chromadb"] is True
            assert "version" in data
            assert "model" in data

    def test_health_degraded(self, client):
        with patch("app.main.check_ollama_health", new_callable=AsyncMock, return_value=False), \
             patch("app.main.check_chroma_health", new_callable=AsyncMock, return_value=True):
            resp = client.get("/api/v1/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["ollama"] is False

    def test_health_all_down(self, client):
        with patch("app.main.check_ollama_health", new_callable=AsyncMock, return_value=False), \
             patch("app.main.check_chroma_health", new_callable=AsyncMock, return_value=False):
            resp = client.get("/api/v1/health")
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["ollama"] is False
            assert data["chromadb"] is False


class TestChatEndpoint:

    def test_chat_streams_tokens(self, client):
        async def mock_stream(*args, **kwargs):
            for token in ["Hello", " ", "world", "!"]:
                yield token

        with patch("app.main.stream_chat", side_effect=mock_stream):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "Hi"},
            )
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]

            # Parse SSE events
            tokens = []
            for line in resp.text.strip().split("\n"):
                if line.startswith("data: "):
                    data = json.loads(line[6:])
                    if "token" in data:
                        tokens.append(data["token"])
                    if data.get("done"):
                        break

            assert "Hello" in tokens
            assert "world" in tokens

    def test_chat_with_context(self, client):
        async def mock_stream(*args, **kwargs):
            yield "OK"

        with patch("app.main.stream_chat", side_effect=mock_stream) as mock:
            resp = client.post(
                "/api/v1/chat",
                json={
                    "message": "How to create a template?",
                    "context": {"page": "/templates"},
                    "history": [
                        {"role": "user", "content": "Hello"},
                        {"role": "assistant", "content": "Hi!"},
                    ],
                },
            )
            assert resp.status_code == 200

    def test_chat_empty_message_rejected(self, client):
        resp = client.post("/api/v1/chat", json={})
        assert resp.status_code == 422  # Validation error

    def test_chat_error_handling(self, client):
        async def mock_stream(*args, **kwargs):
            raise Exception("LLM error")
            yield  # Make it a generator

        with patch("app.main.stream_chat", side_effect=mock_stream):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "test"},
            )
            assert resp.status_code == 200
            # Should contain error in stream
            assert "error" in resp.text or "done" in resp.text


class TestIndexEndpoint:

    def test_index_trigger(self, client):
        with patch("app.main.settings.admin_token", "secret"), \
             patch("app.indexer.index_documents", return_value=42):
            resp = client.post("/api/v1/index", headers={"X-Admin-Token": "secret"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["indexed_chunks"] == 42
            assert data["rebuild"] is False

    def test_index_rebuild(self, client):
        with patch("app.main.settings.admin_token", "secret"), \
             patch("app.indexer.index_documents", return_value=100):
            resp = client.post(
                "/api/v1/index?rebuild=true", headers={"X-Admin-Token": "secret"}
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["rebuild"] is True

    def test_index_disabled_without_token(self, client):
        with patch("app.main.settings.admin_token", ""):
            resp = client.post("/api/v1/index")
            assert resp.status_code == 503

    def test_index_rejects_wrong_token(self, client):
        with patch("app.main.settings.admin_token", "secret"):
            resp = client.post("/api/v1/index", headers={"X-Admin-Token": "nope"})
            assert resp.status_code == 401


class TestOpenAPI:

    def test_docs_available(self, client):
        resp = client.get("/api/v1/docs")
        assert resp.status_code == 200

    def test_openapi_schema(self, client):
        resp = client.get("/api/v1/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert "/api/v1/health" in schema["paths"]
        assert "/api/v1/chat" in schema["paths"]


class TestChatRequestBounds:
    """
    Codex M3: the concurrency cap limits how many generations run at once and
    says nothing about how large or how long any one of them is. Four callers
    could hold every slot for the full Ollama timeout with a prompt the size of
    a book.
    """

    def _stream(self):
        async def mock_stream(*args, **kwargs):
            yield "ok"
        return mock_stream

    def test_oversized_message_is_refused(self, client):
        from app.config import settings

        resp = client.post(
            "/api/v1/chat",
            json={"message": "x" * (settings.chat_max_message_chars + 1)},
        )
        assert resp.status_code == 413

    def test_message_at_the_limit_is_accepted(self, client):
        from app.config import settings

        with patch("app.main.stream_chat", side_effect=self._stream()):
            resp = client.post(
                "/api/v1/chat",
                json={"message": "x" * settings.chat_max_message_chars},
            )
        assert resp.status_code == 200

    def test_blank_message_is_refused(self, client):
        resp = client.post("/api/v1/chat", json={"message": "   "})
        assert resp.status_code == 400

    def test_history_is_trimmed_to_the_most_recent_turns(self, client):
        # Trimmed rather than rejected: dropping the oldest turns costs a little
        # context, while a 413 mid-conversation ends it.
        from app.config import settings

        captured = {}

        async def mock_stream(*args, **kwargs):
            captured.update(kwargs)
            yield "ok"

        history = [{"role": "user", "content": f"turn {i}"} for i in range(200)]
        with patch("app.main.stream_chat", side_effect=mock_stream):
            resp = client.post("/api/v1/chat", json={"message": "hi", "history": history})

        assert resp.status_code == 200
        assert len(captured["history"]) <= settings.chat_max_history_turns
        # The turns kept are the recent ones, not the first ones.
        assert captured["history"][-1]["content"] == "turn 199"

    def test_history_is_trimmed_by_total_size(self, client):
        from app.config import settings

        captured = {}

        async def mock_stream(*args, **kwargs):
            captured.update(kwargs)
            yield "ok"

        history = [{"role": "user", "content": "x" * 5000} for _ in range(10)]
        with patch("app.main.stream_chat", side_effect=mock_stream):
            client.post("/api/v1/chat", json={"message": "hi", "history": history})

        total = sum(len(t["content"]) for t in captured["history"])
        assert total <= settings.chat_max_history_chars

    def test_page_context_is_truncated(self, client):
        captured = {}

        async def mock_stream(*args, **kwargs):
            captured.update(kwargs)
            yield "ok"

        with patch("app.main.stream_chat", side_effect=mock_stream):
            client.post(
                "/api/v1/chat",
                json={"message": "hi", "context": {"page": "/x" * 5000}},
            )
        assert len(captured["page_context"]) <= 200

    def test_a_generation_that_will_not_stop_is_cut(self, client):
        # The slot it holds is one of only chat_max_concurrency, so an endless
        # stream is a denial of service against the other three. A deadline
        # already in the past is the same code path as one that runs out.
        from app.config import settings

        emitted = 0

        async def endless(*args, **kwargs):
            nonlocal emitted
            for _ in range(100):
                emitted += 1
                yield "token"

        with patch("app.main.stream_chat", side_effect=endless), \
             patch.object(settings, "chat_deadline_seconds", -1):
            resp = client.post("/api/v1/chat", json={"message": "hi"})

        assert resp.status_code == 200
        assert "timed out" in resp.text
        # Cut, not drained: the generator does not run to completion.
        assert emitted < 100
