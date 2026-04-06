"""Long-term memory using ChromaDB for embedding-based retrieval."""

from __future__ import annotations

import uuid
from typing import Any

from ai_dev_team.config import get_settings


class LongTermMemory:
    """
    Vector-based memory for storing and retrieving past decisions,
    code patterns, and project context.
    """

    def __init__(
        self,
        collection_name: str = "agent_memory",
        persist_dir: str | None = None,
    ):
        settings = get_settings()
        self._persist_dir = persist_dir or str(settings.memory.chroma_persist_dir)
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None

    def _ensure_initialized(self) -> None:
        if self._client is not None:
            return

        import chromadb

        self._client = chromadb.PersistentClient(path=self._persist_dir)
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def store(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> str:
        """Store a text document with optional metadata. Returns the document ID."""
        self._ensure_initialized()
        doc_id = doc_id or str(uuid.uuid4())
        self._collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[metadata or {}],
        )
        return doc_id

    def query(
        self,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query for similar documents. Returns list of {id, text, metadata, distance}."""
        self._ensure_initialized()
        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        documents: list[dict[str, Any]] = []
        ids = results.get("ids", [[]])[0]
        texts = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for i in range(len(ids)):
            documents.append({
                "id": ids[i],
                "text": texts[i] if texts else "",
                "metadata": metadatas[i] if metadatas else {},
                "distance": distances[i] if distances else 0.0,
            })

        return documents

    def delete(self, doc_id: str) -> None:
        """Delete a document by ID."""
        self._ensure_initialized()
        self._collection.delete(ids=[doc_id])

    @property
    def count(self) -> int:
        """Number of documents stored."""
        self._ensure_initialized()
        return self._collection.count()
