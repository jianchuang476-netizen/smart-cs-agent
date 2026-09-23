from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import ActionType, ApprovalStatus


class ApprovalDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str | None = Field(default=None, max_length=1000)
    version: int = Field(ge=1)


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    session_id: str
    user_id: str
    action_type: ActionType
    payload: dict[str, Any]
    status: ApprovalStatus
    version: int
    requested_by: str
    decided_by: str | None
    decision_comment: str | None
    error_message: str | None
    result: dict[str, Any]
    notified_at: datetime | None
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
