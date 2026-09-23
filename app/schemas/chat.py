from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str | None = None
    client_message_id: str | None = Field(default=None, max_length=64)


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    status: str
    last_message_at: datetime | None
    created_at: datetime


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    role: str
    content: str
    event_metadata: dict[str, Any]
    created_at: datetime


class ChatSseEvent(BaseModel):
    event: Literal[
        "session",
        "token",
        "tool_call",
        "citation",
        "approval_required",
        "done",
        "error",
    ]
    data: dict[str, Any]
