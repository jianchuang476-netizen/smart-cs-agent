from __future__ import annotations

import asyncio
from pathlib import Path

from app.db.models import JobStatus, KnowledgeDocument, KnowledgeIngestionJob
from app.db.session import SessionLocal
from app.services.rag_service import KnowledgeIngestor
from app.worker.celery_app import celery_app


async def _ingest_document(
    document_id: str,
    job_id: str,
    stored_path: str,
    title: str,
    version: str,
    source_uri: str,
) -> dict:
    async with SessionLocal() as session:
        job = await session.get(KnowledgeIngestionJob, job_id)
        document = await session.get(KnowledgeDocument, document_id)
        if job is None or document is None:
            raise LookupError("文档或任务不存在")
        job.status = JobStatus.RUNNING
        job.progress = 10
        await session.commit()

    try:
        ingestor = KnowledgeIngestor()
        chunk_count = await ingestor.ingest_path(
            document_id=document_id,
            path=Path(stored_path),
            title=title,
            source_uri=source_uri or stored_path,
            version=version,
        )
    except Exception as exc:
        async with SessionLocal() as session:
            job = await session.get(KnowledgeIngestionJob, job_id)
            document = await session.get(KnowledgeDocument, document_id)
            if job:
                job.status = JobStatus.FAILED
                job.error = str(exc)[:2000]
            if document:
                document.status = "failed"
            await session.commit()
        raise

    async with SessionLocal() as session:
        job = await session.get(KnowledgeIngestionJob, job_id)
        document = await session.get(KnowledgeDocument, document_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.progress = 100
            job.document_id = document_id
        if document:
            document.status = "active"
            document.chunk_count = chunk_count
        await session.commit()
    return {"document_id": document_id, "chunks": chunk_count}


@celery_app.task(name="knowledge.ingest_document", autoretry_for=(Exception,), retry_backoff=True)
def ingest_document(
    document_id: str,
    job_id: str,
    stored_path: str,
    title: str,
    version: str,
    source_uri: str,
) -> dict:
    return asyncio.run(
        _ingest_document(
            document_id,
            job_id,
            stored_path,
            title,
            version,
            source_uri,
        )
    )
