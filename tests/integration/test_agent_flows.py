from __future__ import annotations

from langchain_core.language_models.fake_chat_models import FakeListChatModel
from sqlalchemy import func, select

from app.config import get_settings
from app.core.agent import AgentRuntime
from app.db.models import (
    Approval,
    ApprovalStatus,
    ChatMessage,
    ConversationSession,
    Notification,
    Order,
    RefundRequest,
    User,
)
from app.db.seed import seed_database
from app.db.session import SessionLocal
from app.services.approval_service import ApprovalService
from app.services.order_service import OrderService
from app.services.vector_db import SearchDocument


class FakeRetriever:
    async def search(self, query: str, top_k: int | None = None):
        return [
            SearchDocument(
                id="policy-1",
                content="七天无理由退货应在签收后七日内申请。",
                source="return_policy.md",
                title="七天无理由退货政策",
                score=0.98,
                metadata={},
            )
        ]


async def make_context(title: str) -> tuple[str, str, str]:
    await seed_database()
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == "customer@example.com"))
        assert user is not None
        order = await session.scalar(select(Order).where(Order.user_id == user.id))
        assert order is not None
        conversation = ConversationSession(user_id=user.id, title=title)
        session.add(conversation)
        await session.commit()
        return user.id, order.order_no, conversation.id


async def test_knowledge_and_order_flows():
    user_id, order_no, session_id = await make_context("知识订单")
    runtime = AgentRuntime(
        get_settings(),
        model=FakeListChatModel(responses=["签收后七日内可以申请。[1]"]),
        retriever=FakeRetriever(),
    )
    await runtime.startup()
    try:
        knowledge_events = [
            event
            async for event in runtime.stream_chat(
                message="七天无理由退货多久？",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        assert any(event["event"] == "citation" for event in knowledge_events)
        assert knowledge_events[-1]["event"] == "done"

        order_events = [
            event
            async for event in runtime.stream_chat(
                message=f"查询订单 {order_no} 的物流",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        text = "".join(
            event["data"]["content"] for event in order_events if event["event"] == "token"
        )
        assert order_no in text
    finally:
        await runtime.shutdown()


async def test_refund_approval_resume_is_idempotent():
    user_id, order_no, session_id = await make_context("退款审批")
    runtime = AgentRuntime(
        get_settings(),
        model=FakeListChatModel(responses=["已完成。"]),
        retriever=FakeRetriever(),
    )
    await runtime.startup()
    try:
        events = [
            event
            async for event in runtime.stream_chat(
                message=f"订单 {order_no} 我要退款 50 元",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        approval_id = next(
            event["data"]["approval_id"]
            for event in events
            if event["event"] == "approval_required"
        )

        async with SessionLocal() as session:
            service = ApprovalService(session)
            approval = await service.get(approval_id)
            assert approval is not None
            await service.decide(
                approval_id,
                decision=ApprovalStatus.APPROVED,
                comment="同意",
                version=approval.version,
                decided_by="agent-1",
            )
            await session.commit()

        resumed = [
            event
            async for event in runtime.stream_resume(
                approval_id=approval_id,
                decision="approved",
                comment="同意",
                decided_by="agent-1",
            )
        ]
        assert resumed[-1]["event"] == "done"

        async with SessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(RefundRequest)
                .where(RefundRequest.approval_id == approval_id)
            )
            assert count == 1
    finally:
        await runtime.shutdown()


async def test_refund_rejection_does_not_create_refund():
    user_id, order_no, session_id = await make_context("退款拒绝")
    runtime = AgentRuntime(
        get_settings(),
        model=FakeListChatModel(responses=["已拒绝。"]),
        retriever=FakeRetriever(),
    )
    await runtime.startup()
    try:
        events = [
            event
            async for event in runtime.stream_chat(
                message=f"订单 {order_no} 我要退款 50 元",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        approval_id = next(
            event["data"]["approval_id"]
            for event in events
            if event["event"] == "approval_required"
        )
        async with SessionLocal() as session:
            service = ApprovalService(session)
            approval = await service.get(approval_id)
            assert approval is not None
            await service.decide(
                approval_id,
                decision=ApprovalStatus.REJECTED,
                comment="不同意",
                version=approval.version,
                decided_by="agent-1",
            )
            await session.commit()

        resumed = [
            event
            async for event in runtime.stream_resume(
                approval_id=approval_id,
                decision="rejected",
                comment="不同意",
                decided_by="agent-1",
            )
        ]
        assert resumed[-1]["event"] == "done"
        async with SessionLocal() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(RefundRequest)
                .where(RefundRequest.approval_id == approval_id)
            )
            assert count == 0
    finally:
        await runtime.shutdown()


async def test_invalid_order_is_rejected_before_approval():
    await seed_database()
    async with SessionLocal() as session:
        user = await session.scalar(select(User).where(User.email == "customer@example.com"))
        other_user = await session.scalar(
            select(User).where(User.email == "customer20@example.com")
        )
        assert user is not None and other_user is not None
        other_order = await session.scalar(select(Order).where(Order.user_id == other_user.id))
        conversation = ConversationSession(user_id=user.id, title="非法订单")
        session.add(conversation)
        await session.commit()
        user_id = user.id
        order_no = other_order.order_no
        session_id = conversation.id

    runtime = AgentRuntime(
        get_settings(),
        model=FakeListChatModel(responses=["不应调用模型。"]),
        retriever=FakeRetriever(),
    )
    await runtime.startup()
    try:
        events = [
            event
            async for event in runtime.stream_chat(
                message=f"订单 {order_no} 我要退款 50 元",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        assert not any(event["event"] == "approval_required" for event in events)
        text = "".join(event["data"]["content"] for event in events if event["event"] == "token")
        assert "不属于当前登录用户" in text
        async with SessionLocal() as session:
            count = await session.scalar(
                select(func.count()).select_from(Approval).where(Approval.session_id == session_id)
            )
            assert count == 0
    finally:
        await runtime.shutdown()


async def test_execution_failure_is_reported_to_customer(monkeypatch):
    user_id, order_no, session_id = await make_context("执行失败反馈")
    runtime = AgentRuntime(
        get_settings(),
        model=FakeListChatModel(responses=["不应调用模型。"]),
        retriever=FakeRetriever(),
    )
    await runtime.startup()
    try:
        events = [
            event
            async for event in runtime.stream_chat(
                message=f"订单 {order_no} 我要退款 50 元",
                user_id=user_id,
                session_id=session_id,
                roles=["customer"],
            )
        ]
        approval_id = next(
            event["data"]["approval_id"]
            for event in events
            if event["event"] == "approval_required"
        )

        async def fail_refund(*args, **kwargs):
            raise ValueError("模拟退款系统故障")

        monkeypatch.setattr(OrderService, "create_refund", fail_refund)

        async with SessionLocal() as session:
            service = ApprovalService(session)
            approval = await service.get(approval_id)
            assert approval is not None
            await service.decide(
                approval_id,
                decision=ApprovalStatus.APPROVED,
                comment="同意",
                version=approval.version,
                decided_by="agent-1",
            )
            await session.commit()

        resumed = [
            event
            async for event in runtime.stream_resume(
                approval_id=approval_id,
                decision="approved",
                comment="同意",
                decided_by="agent-1",
            )
        ]
        assert resumed[-1]["event"] == "done"
        async with SessionLocal() as session:
            approval = await session.get(Approval, approval_id)
            assert approval is not None
            assert approval.status == ApprovalStatus.FAILED
            assert approval.error_message
            message = await session.scalar(
                select(ChatMessage).where(
                    ChatMessage.client_message_id == f"approval:{approval_id}:result"
                )
            )
            assert message is not None
            assert message.event_metadata["approval_status"] == "failed"
            notification = await session.scalar(
                select(Notification).where(
                    Notification.idempotency_key == f"approval:{approval_id}:in_app"
                )
            )
            assert notification is not None

    finally:
        await runtime.shutdown()
