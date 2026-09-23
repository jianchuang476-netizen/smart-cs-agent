from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer

from app.config import Settings, get_settings
from app.core.security import sanitize_retrieved_text


@dataclass(slots=True)
class SearchDocument:
    id: str
    content: str
    source: str
    title: str
    score: float
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "source": self.source,
            "title": self.title,
            "score": self.score,
            "metadata": self.metadata,
        }


def tokenize(text: str) -> list[str]:
    return re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower())


class VectorDB:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: chromadb.ClientAPI | None = None
        self._collection: Collection | None = None
        self._embedding_model: SentenceTransformer | None = None
        self._reranker: CrossEncoder | None = None
        self._lock = asyncio.Lock()

    @property
    def collection(self) -> Collection:
        if self._collection is None:
            if self.settings.chroma_host:
                self._client = chromadb.HttpClient(
                    host=self.settings.chroma_host,
                    port=self.settings.chroma_port,
                )
            else:
                self._client = chromadb.EphemeralClient()
            self._collection = self._client.get_or_create_collection(
                name=self.settings.chroma_collection,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            if self._embedding_model is None:
                self._embedding_model = await asyncio.to_thread(
                    SentenceTransformer,
                    self.settings.embedding_model,
                    cache_folder=str(self.settings.model_cache_dir),
                )
            vectors = await asyncio.to_thread(
                self._embedding_model.encode,
                texts,
                normalize_embeddings=True,
            )
        return vectors.tolist()

    async def rerank(
        self, query: str, documents: list[SearchDocument], top_k: int
    ) -> list[SearchDocument]:
        if not documents or not self.settings.reranker_enabled:
            return documents[:top_k]
        async with self._lock:
            if self._reranker is None:
                self._reranker = await asyncio.to_thread(
                    CrossEncoder,
                    self.settings.reranker_model,
                    cache_folder=str(self.settings.model_cache_dir),
                )
            scores = await asyncio.to_thread(
                self._reranker.predict,
                [(query, doc.content) for doc in documents],
            )
        ranked = sorted(
            zip(documents, scores, strict=False),
            key=lambda item: float(item[1]),
            reverse=True,
        )
        return [
            SearchDocument(
                id=doc.id,
                content=doc.content,
                source=doc.source,
                title=doc.title,
                score=float(score),
                metadata=doc.metadata,
            )
            for doc, score in ranked[:top_k]
        ]

    async def upsert(
        self,
        *,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not ids:
            return
        sanitized = [sanitize_retrieved_text(document) for document in documents]
        embeddings = await self.embed(sanitized)
        await asyncio.to_thread(
            self.collection.upsert,
            ids=ids,
            documents=sanitized,
            metadatas=metadatas,
            embeddings=embeddings,
        )

    async def delete_document(self, document_id: str) -> None:
        await asyncio.to_thread(
            self.collection.delete,
            where={"document_id": document_id},
        )


class HybridRetriever:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.vector_db = VectorDB(self.settings)

    async def _dense_search(self, query: str, limit: int) -> list[SearchDocument]:
        query_embedding = (await self.vector_db.embed([query]))[0]
        result = await asyncio.to_thread(
            self.vector_db.collection.query,
            query_embeddings=[query_embedding],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        return [
            SearchDocument(
                id=doc_id,
                content=document,
                source=str(metadata.get("source", "")),
                title=str(metadata.get("title", "")),
                score=1.0 - float(distance),
                metadata=metadata,
            )
            for doc_id, document, metadata, distance in zip(
                ids, documents, metadatas, distances, strict=False
            )
        ]

    async def _bm25_search(self, query: str, limit: int) -> list[SearchDocument]:
        result = await asyncio.to_thread(
            self.vector_db.collection.get,
            include=["documents", "metadatas"],
        )
        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])
        if not ids:
            return []

        corpus = [tokenize(document) for document in documents]
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenize(query))
        ranked_indices = sorted(
            range(len(scores)), key=lambda index: float(scores[index]), reverse=True
        )[:limit]
        return [
            SearchDocument(
                id=ids[index],
                content=documents[index],
                source=str(metadatas[index].get("source", "")),
                title=str(metadatas[index].get("title", "")),
                score=float(scores[index]),
                metadata=metadatas[index],
            )
            for index in ranked_indices
        ]

    @staticmethod
    def _rrf(
        dense: list[SearchDocument],
        sparse: list[SearchDocument],
        *,
        constant: int = 60,
    ) -> list[SearchDocument]:
        scores: dict[str, float] = {}
        docs: dict[str, SearchDocument] = {}
        for ranked in (dense, sparse):
            for rank, document in enumerate(ranked, start=1):
                scores[document.id] = scores.get(document.id, 0.0) + 1.0 / (constant + rank)
                docs[document.id] = document
        ordered = sorted(scores, key=scores.get, reverse=True)
        return [
            SearchDocument(
                id=doc_id,
                content=docs[doc_id].content,
                source=docs[doc_id].source,
                title=docs[doc_id].title,
                score=scores[doc_id],
                metadata=docs[doc_id].metadata,
            )
            for doc_id in ordered
        ]

    async def search(self, query: str, top_k: int | None = None) -> list[SearchDocument]:
        final_k = top_k or self.settings.rag_final_k
        candidate_k = max(self.settings.rag_top_k, final_k)
        dense = await self._dense_search(query, candidate_k)
        sparse = await self._bm25_search(query, candidate_k)
        fused = self._rrf(dense, sparse)[:candidate_k]
        try:
            return await self.vector_db.rerank(query, fused, final_k)
        except Exception:
            return fused[:final_k]
