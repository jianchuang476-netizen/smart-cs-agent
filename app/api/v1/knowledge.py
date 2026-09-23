from __future__ import annotations

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.config import Settings, get_settings
from app.db.models import JobStatus, KnowledgeDocument, KnowledgeIngestionJob, User, UserRole
from app.db.session import get_db
from app.schemas.knowledge import (
    KnowledgeDocumentRead,
    SearchResult,
    SearchTestRequest,
    SearchTestResponse,
)
from app.services.rag_service import KnowledgeIngestor, KnowledgeService

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
admin_only = require_roles(UserRole.ADMIN)


@router.get("/documents", response_model=list[KnowledgeDocumentRead])
async def list_documents(
    _user: User = Depends(admin_only),
    session: AsyncSession = Depends(get_db),
) -> list[KnowledgeDocument]:
    return await KnowledgeService(session).list_documents()


@router.post("/documents", response_model=KnowledgeDocumentRead)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    version: str = Form("1.0"),
    source_uri: str = Form(""),
    _user: User = Depends(admin_only),
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> KnowledgeDocument:
    filename = Path(file.filename or "document.md").name
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".docx", ".md", ".markdown", ".txt"}:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="仅支持 PDF、DOCX、Markdown 和 TXT",
        )
    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少文件名")

    stored_name = f"{uuid.uuid4().hex}{suffix}"
    stored_path = settings.upload_dir / stored_name
    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="文件过大")
    async with aiofiles.open(stored_path, "wb") as output:
        await output.write(content)

    content_hash = KnowledgeIngestor.content_hash(stored_path)
    existing = await session.scalar(
        select(KnowledgeDocument).where(KnowledgeDocument.content_hash == content_hash)
    )
    if existing:
        return existing

    document = KnowledgeDocument(
        title=title,
        filename=filename,
        version=version,
        source_uri=source_uri or str(stored_path),
        content_hash=content_hash,
        status="pending",
        metadata_json={"stored_path": str(stored_path)},
    )
    session.add(document)
    await session.flush()
    job = KnowledgeIngestionJob(
        document_id=document.id,
        status=JobStatus.PENDING,
        filename=filename,
        stored_path=str(stored_path),
    )
    session.add(job)
    await session.flush()

    from app.worker.tasks import ingest_document

    ingest_document.delay(document.id, job.id, str(stored_path), title, version, source_uri)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: str,
    _user: User = Depends(admin_only),
    session: AsyncSession = Depends(get_db),
) -> None:
    deleted = await KnowledgeService(session).delete_document(document_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")


@router.post("/search-test", response_model=SearchTestResponse)
async def search_test(
    payload: SearchTestRequest,
    _user: User = Depends(admin_only),
    session: AsyncSession = Depends(get_db),
) -> SearchTestResponse:
    documents = await KnowledgeService(session).search(payload.query, payload.top_k)
    return SearchTestResponse(
        query=payload.query,
        results=[
            SearchResult(
                content=document.content,
                source=document.source,
                title=document.title,
                score=document.score,
            )
            for document in documents
        ],
    )


@router.get("/jobs/{job_id}", response_model=dict)
async def get_job(
    job_id: str,
    _user: User = Depends(admin_only),
    session: AsyncSession = Depends(get_db),
) -> dict:
    job = await session.get(KnowledgeIngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    return {
        "id": job.id,
        "document_id": job.document_id,
        "status": job.status.value,
        "progress": job.progress,
        "error": job.error,
    }
