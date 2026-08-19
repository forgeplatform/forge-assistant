"""Application configuration from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3:1b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout: int = 300

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8000
    chroma_collection: str = "forail_docs"

    # RAG
    rag_top_k: int = 3
    rag_chunk_size: int = 500
    rag_chunk_overlap: int = 50

    # App
    app_name: str = "Forail Assistant"
    app_version: str = "2026.06.0"
    log_level: str = "INFO"
    cors_origins: str = "*"

    # Admin token required to call the re-indexing endpoint. When empty the
    # endpoint is disabled (fail closed). Startup auto-indexing is unaffected.
    admin_token: str = ""

    # Shared bearer token required to call the chat endpoint (needtofix M14).
    # When empty the endpoint is open (backwards compatible) but a warning is
    # logged at startup; set it to require callers to send `Authorization:
    # Bearer <token>` (the gateway/frontend injects it).
    chat_token: str = ""

    # Max concurrent chat generations (needtofix M14). Each request drives an
    # LLM generation up to ollama_timeout seconds; without a cap a flood
    # exhausts GPU/CPU. Excess requests get 429.
    chat_max_concurrency: int = 4

    # Bounds on a single request (Codex M3). The concurrency cap limits how many
    # generations run at once, but says nothing about how large or how long any
    # one of them is -- four callers could hold every slot for the full Ollama
    # timeout with a prompt the size of a book.
    #
    # A question is a question: 4000 characters is longer than anyone types.
    chat_max_message_chars: int = 4000
    # Turns of prior conversation kept. Each one is re-sent to the model, so an
    # unbounded history is an unbounded prompt, paid for on every request.
    chat_max_history_turns: int = 20
    chat_max_history_chars: int = 16000
    # Hard ceiling on one streamed response, independent of the model's own
    # timeout. A generation that will not stop still ends.
    chat_deadline_seconds: int = 180

    model_config = {"env_prefix": "FORAIL_ASSISTANT_"}


settings = Settings()
