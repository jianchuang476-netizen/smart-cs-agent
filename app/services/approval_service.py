from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ActionType, Approval, ApprovalStatus


class ApprovalConflictError(ValueError):
    pass


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_pending(
        self,
        *,
        session_id: str,
        user_id: str,
        action_type: ActionType,
        payload: dict[str, Any],
        idempotency_key: str,
        expires_in_minutes: int = 30,
    ) -> Approval:
        existing = await self.session.scalar(
            select(Approval).where(Approval.idempotency_key == idempotency_key)
        )
        if existing:
            return existing

        approval = Approval(
            session_id=session_id,
            user_id=user_id,
            action_type=action_type,
            payload=payload,
            status=ApprovalStatus.PENDING,
            version=1,
            requested_by="agent",
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_in_minutes),
            idempotency_key=idempotency_key,
        )
        self.session.add(approval)
        await self.session.flush()
        return approval

    async def get(self, approval_id: str) -> Approval | None:
        return await self.session.get(Approval, approval_id)

    async def list_by_status(self, status: ApprovalStatus, *, limit: int = 100) -> list[Approval]:
        result = await self.session.execute(
            select(Approval)
            .where(Approval.status == status)
            .order_by(Approval.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def decide(
        self,
        approval_id: str,
        *,
        decision: ApprovalStatus,
        comment: str | None,
        version: int,
        decided_by: str,
    ) -> Approval:
        approval = await self.session.get(Approval, approval_id)
        if approval is None:
            raise LookupError("审批记录不存在")
        if approval.status != ApprovalStatus.PENDING:
            if approval.status == decision:
                return approval
            raise ApprovalConflictError("审批已处理，不能重复决策")
        if approval.version != version:
            raise ApprovalConflictError("审批版本已变化，请刷新后重试")
        expires_at = approval.expires_at
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at and expires_at < datetime.now(UTC):
            approval.status = ApprovalStatus.EXPIRED
            raise ApprovalConflictError("审批已过期")

        approval.status = decision
        approval.decided_by = decided_by
        approval.decision_comment = comment
        approval.version += 1
        await self.session.flush()
        return approval

    async def mark_executed(
        self, approval: Approval, result: dict[str, Any] | None = None
    ) -> Approval:
        if approval.status == ApprovalStatus.EXECUTED:
            return approval
        if approval.status != ApprovalStatus.APPROVED:
            raise ApprovalConflictError("只有已批准的审批才能执行")
        approval.status = ApprovalStatus.EXECUTED
        approval.result = result or {}
        approval.error_message = None
        approval.executed_at = datetime.now(UTC)
        approval.version += 1
        await self.session.flush()
        return approval

    async def mark_failed(self, approval: Approval, error_message: str) -> Approval:
        if approval.status == ApprovalStatus.EXECUTED:
            return approval
        approval.status = ApprovalStatus.FAILED
        approval.error_message = error_message[:2000]
        approval.version += 1
        await self.session.flush()
        return approval

    async def mark_notified(self, approval: Approval) -> Approval:
        approval.notified_at = datetime.now(UTC)
        await self.session.flush()
        return approval
