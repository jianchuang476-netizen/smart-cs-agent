from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, rate_limit, verify_csrf
from app.core.sse import format_sse
from app.db.models import ChatMessage, ConversationSession, User
from app.db.session import SessionLocal, get_db
from app.schemas.chat import ChatRequest

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
    request: Request,
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    _: None = Depends(rate_limit),
    __: None = Depends(verify_csrf),
) -> StreamingResponse:
    conversation_id = payload.session_id
    if conversation_id:
        conversation = await session.get(ConversationSession, conversation_id)
        if conversation is None or conversation.user_id != user.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        conversation = ConversationSession(user_id=user.id, title=payload.message[:60])
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id

    if payload.client_message_id:
        existing = await session.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == conversation_id,
                ChatMessage.client_message_id == payload.client_message_id,
            )
        )
    else:
        existing = None
    if existing is None:
        session.add(
            ChatMessage(
                session_id=conversation_id,
                role="user",
                content=payload.message,
                client_message_id=payload.client_message_id,
            )
        )
        await session.flush()
    await session.commit()

    agent = request.app.state.agent
    user_id = user.id
    roles = [user.role.value]
    trace_id = getattr(request.state, "trace_id", None)

    async def generate() -> AsyncIterator[str]:
        yield format_sse("session", {"session_id": conversation_id})
        chunks: list[str] = []
        citations: list[dict] = []
        approval: dict | None = None
        error: str | None = None
        try:
            async for event in agent.stream_chat(
                message=payload.message,
                user_id=user_id,
                session_id=conversation_id,
                roles=roles,
                trace_id=trace_id,
            ):
                if event["event"] == "token":
                    chunks.append(event["data"].get("content", ""))
                elif event["event"] == "citation":
                    citations.append(event["data"])
                elif event["event"] == "approval_required":
                    approval = event["data"]
                elif event["event"] == "error":
                    error = event["data"].get("message")
                yield format_sse(event["event"], event["data"])
        finally:
            content = "".join(chunks)
            metadata: dict = {"citations": citations}
            if approval:
                metadata["approval"] = approval
                content = content or "该操作需要人工审批，申请已提交。"
            if error:
                metadata["error"] = error
                content = content or f"处理失败：{error}"
            if content:
                async with SessionLocal() as persist_session:
                    persist_session.add(
                        ChatMessage(
                            session_id=conversation_id,
                            role="assistant",
                            content=content,
                            event_metadata=metadata,
                        )
                    )
                    conversation_record = await persist_session.get(
                        ConversationSession, conversation_id
                    )
                    if conversation_record is not None:
                        conversation_record.last_message_at = conversation_record.updated_at
                    await persist_session.commit()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
