from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    filename: str
    version: str
    effective_date: datetime | None
    source_uri: str | None
    content_hash: str
    status: str
    chunk_count: int
    metadata_json: dict[str, Any]
    created_at: datetime


class SearchTestRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000)
    top_k: int = Field(default=4, ge=1, le=20)


class SearchResult(BaseModel):
    content: str
    source: str
    title: str
    score: float


class SearchTestResponse(BaseModel):
    query: str
    results: list[SearchResult]
