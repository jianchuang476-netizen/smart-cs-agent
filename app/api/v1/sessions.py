from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import ChatMessage, ConversationSession, User, UserRole
from app.db.session import get_db
from app.schemas.chat import MessageRead, SessionRead

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=list[SessionRead])
async def list_sessions(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ConversationSession]:
    statement = select(ConversationSession).order_by(ConversationSession.updated_at.desc())
    if user.role == UserRole.CUSTOMER:
        statement = statement.where(ConversationSession.user_id == user.id)
    result = await session.execute(statement.limit(200))
    return list(result.scalars().all())


@router.get("/{session_id}/messages", response_model=list[MessageRead])
async def list_messages(
    session_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ChatMessage]:
    conversation = await session.get(ConversationSession, session_id)
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    if user.role == UserRole.CUSTOMER and conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")

    result = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc())
    )
    return list(result.scalars().all())
