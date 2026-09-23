from __future__ import annotations

import hashlib
from pathlib import Path

from docx import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import KnowledgeDocument
from app.services.vector_db import HybridRetriever, SearchDocument


class DocumentParseError(ValueError):
    pass


class KnowledgeIngestor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.retriever = HybridRetriever(self.settings)
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.settings.rag_chunk_size,
            chunk_overlap=self.settings.rag_chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        )

    @staticmethod
    def content_hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def extract_text(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if suffix == ".docx":
            document = Document(str(path))
            return "\n".join(paragraph.text for paragraph in document.paragraphs)
        if suffix in {".md", ".markdown", ".txt"}:
            return path.read_text(encoding="utf-8")
        raise DocumentParseError(f"不支持的文件类型: {suffix}")

    async def ingest_path(
        self,
        *,
        document_id: str,
        path: Path,
        title: str,
        source_uri: str,
        version: str,
    ) -> int:
        text = self.extract_text(path).strip()
        if not text:
            raise DocumentParseError("文档没有可提取的文本")
        chunks = self.splitter.split_text(text)
        ids = [f"{document_id}:{index}" for index in range(len(chunks))]
        metadatas = [
            {
                "document_id": document_id,
                "title": title,
                "source": source_uri,
                "version": version,
                "chunk_index": index,
            }
            for index in range(len(chunks))
        ]
        await self.retriever.vector_db.upsert(
            ids=ids,
            documents=chunks,
            metadatas=metadatas,
        )
        return len(chunks)


class KnowledgeService:
    def __init__(self, session: AsyncSession, ingestor: KnowledgeIngestor | None = None) -> None:
        self.session = session
        self.ingestor = ingestor or KnowledgeIngestor()

    async def list_documents(self) -> list[KnowledgeDocument]:
        result = await self.session.execute(
            select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
        )
        return list(result.scalars().all())

    async def search(self, query: str, top_k: int) -> list[SearchDocument]:
        return await self.ingestor.retriever.search(query, top_k=top_k)

    async def delete_document(self, document_id: str) -> bool:
        document = await self.session.get(KnowledgeDocument, document_id)
        if not document:
            return False
        await self.ingestor.retriever.vector_db.delete_document(document_id)
        document.status = "deleted"
        await self.session.flush()
        return True
