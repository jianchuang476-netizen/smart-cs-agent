from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles, verify_csrf
from app.core.sse import format_sse
from app.db.models import ApprovalStatus, ChatMessage, ConversationSession, User, UserRole
from app.db.session import SessionLocal, get_db
from app.schemas.approvals import ApprovalDecision, ApprovalRead
from app.services.approval_service import ApprovalConflictError, ApprovalService

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalRead])
async def list_approvals(
    status_filter: ApprovalStatus = Query(default=ApprovalStatus.PENDING, alias="status"),
    _user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> list:
    return await ApprovalService(session).list_by_status(status_filter)


@router.post("/{approval_id}/decision")
async def decide_approval(
    approval_id: str,
    payload: ApprovalDecision,
    request: Request,
    user: User = Depends(require_roles(UserRole.AGENT, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
) -> StreamingResponse:
    service = ApprovalService(session)
    try:
        approval = await service.decide(
            approval_id,
            decision=ApprovalStatus(payload.decision),
            comment=payload.comment,
            version=payload.version,
            decided_by=user.id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ApprovalConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await session.commit()

    agent = request.app.state.agent
    trace_id = getattr(request.state, "trace_id", None)

    async def generate() -> AsyncIterator[str]:
        yield format_sse(
            "session",
            {"session_id": approval.session_id, "approval_id": approval.id},
        )
        chunks: list[str] = []
        try:
            async for event in agent.stream_resume(
                approval_id=approval.id,
                decision=payload.decision,
                comment=payload.comment,
                decided_by=user.id,
                trace_id=trace_id,
            ):
                if event["event"] == "token":
                    chunks.append(event["data"].get("content", ""))
                yield format_sse(event["event"], event["data"])
        finally:
            content = "".join(chunks)
            if content:
                async with SessionLocal() as persist_session:
                    persist_session.add(
                        ChatMessage(
                            session_id=approval.session_id,
                            role="assistant",
                            content=content,
                            event_metadata={
                                "approval_id": approval.id,
                                "decision": payload.decision,
                            },
                        )
                    )
                    conversation = await persist_session.get(
                        ConversationSession, approval.session_id
                    )
                    if conversation:
                        conversation.last_message_at = conversation.updated_at
                    await persist_session.commit()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
