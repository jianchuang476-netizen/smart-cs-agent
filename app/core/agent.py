from __future__ import annotations

import hashlib
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import Settings, get_settings
from app.core.security import sanitize_retrieved_text
from app.core.state import AgentState
from app.db.models import ActionType, Approval, ApprovalStatus, ChatMessage, Notification
from app.db.session import SessionLocal
from app.services.approval_service import ApprovalService
from app.services.audit_service import AuditService
from app.services.order_service import OrderService
from app.services.vector_db import HybridRetriever

logger = logging.getLogger(__name__)

ORDER_PATTERN = re.compile(r"\b(?:ORD|ORDER)[A-Z0-9-]*\d+\b", re.IGNORECASE)


class RouteDecision(BaseModel):
    route: Literal["knowledge", "order", "after_sales"] = Field(
        description="选择处理用户请求的子图"
    )
    intent: str = Field(description="简短意图标签")
    risk_level: Literal["low", "high"] = "low"


class AgentRuntime:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model: BaseChatModel | None = None,
        retriever: HybridRetriever | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.model = model
        self.retriever = retriever or HybridRetriever(self.settings)
        self.graph = None
        self._checkpointer: Any = None
        self._pg_pool: Any = None

    @property
    def checkpointer(self) -> Any:
        return self._checkpointer

    async def startup(self) -> None:
        if self.settings.checkpoint_backend == "postgres":
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
            from psycopg_pool import AsyncConnectionPool

            self._pg_pool = AsyncConnectionPool(
                conninfo=self.settings.checkpoint_database_url,
                min_size=1,
                max_size=5,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0},
            )
            await self._pg_pool.open()
            self._checkpointer = AsyncPostgresSaver(self._pg_pool)
            await self._checkpointer.setup()
        else:
            self._checkpointer = InMemorySaver()

        self.graph = self._build_graph()

    async def shutdown(self) -> None:
        if self._pg_pool is not None:
            await self._pg_pool.close()

    def _get_model(self) -> BaseChatModel:
        if self.model is not None:
            return self.model
        if not self.settings.llm_api_key_value:
            raise RuntimeError("DEEPSEEK_API_KEY 未配置。请在 .env 或 PyCharm 运行配置中设置。")
        self.model = ChatOpenAI(
            model=self.settings.llm_model,
            api_key=self.settings.llm_api_key_value,
            base_url=self.settings.llm_base_url,
            temperature=self.settings.llm_temperature,
        )
        return self.model

    def _build_graph(self):
        assert self._checkpointer is not None
        builder = StateGraph(AgentState)
        builder.add_node("supervisor", self._supervisor_node)
        builder.add_node("knowledge", self._build_knowledge_subgraph())
        builder.add_node("order", self._build_order_subgraph())
        builder.add_node("after_sales", self._build_after_sales_subgraph())
        builder.add_node("response", self._response_node)

        builder.add_edge(START, "supervisor")
        builder.add_conditional_edges(
            "supervisor",
            lambda state: state.get("route", "knowledge"),
            {
                "knowledge": "knowledge",
                "order": "order",
                "after_sales": "after_sales",
            },
        )
        builder.add_edge("knowledge", "response")
        builder.add_edge("order", "response")
        builder.add_edge("after_sales", "response")
        builder.add_edge("response", END)
        return builder.compile(checkpointer=self._checkpointer)

    async def _supervisor_node(self, state: AgentState) -> dict[str, Any]:
        user_text = self._latest_user_text(state)
        route, intent, risk_level = self._heuristic_route(user_text)
        try:
            if self.model is not None or self.settings.llm_api_key_value:
                model = self._get_model().with_structured_output(RouteDecision)
                decision = await model.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                "你是电商售后客服的主管。将请求路由到 knowledge、order "
                                "或 after_sales。退款、补偿、取消订单属于 high risk。"
                            )
                        ),
                        HumanMessage(content=user_text),
                    ]
                )
                if isinstance(decision, RouteDecision):
                    route = decision.route
                    intent = decision.intent
                    risk_level = decision.risk_level
        except Exception as exc:
            logger.warning("supervisor_llm_failed: %s", exc)
        return {"route": route, "intent": intent, "risk_level": risk_level}

    def _build_knowledge_subgraph(self):
        async def knowledge_node(state: AgentState) -> dict[str, Any]:
            query = self._latest_user_text(state)
            try:
                documents = await self.retriever.search(query)
            except Exception as exc:
                logger.exception("rag_search_failed")
                return {
                    "messages": [AIMessage(content="知识库暂时不可用，请稍后重试或转人工客服。")],
                    "errors": [str(exc)],
                }

            citations = [
                {
                    "source": document.source,
                    "title": document.title,
                    "score": document.score,
                    "content": document.content[:300],
                }
                for document in documents
            ]
            if not documents:
                return {
                    "messages": [AIMessage(content="当前知识库中没有找到对应的售后政策。")],
                    "citations": [],
                }

            context = "\n\n".join(
                f"[{index + 1}] {sanitize_retrieved_text(document.content)}"
                for index, document in enumerate(documents)
            )
            model = self._get_model()
            answer = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            "你是电商售后客服。只能依据提供的政策回答，不得编造。"
                            "关键结论后用 [1]、[2] 标注来源；资料不足时明确说明并建议转人工。"
                            f"\n\n售后政策资料：\n{context}"
                        )
                    ),
                    HumanMessage(content=query),
                ]
            )
            return {
                "messages": [answer],
                "retrieved_docs": [document.to_dict() for document in documents],
                "citations": citations,
            }

        graph = StateGraph(AgentState)
        graph.add_node("knowledge_node", knowledge_node)
        graph.add_edge(START, "knowledge_node")
        graph.add_edge("knowledge_node", END)
        return graph.compile()

    def _build_order_subgraph(self):
        async def order_node(state: AgentState) -> dict[str, Any]:
            user_text = self._latest_user_text(state)
            match = ORDER_PATTERN.search(user_text)
            if not match:
                return {
                    "messages": [
                        AIMessage(content="请提供订单号，例如 ORD202600001，我再帮你查询。")
                    ]
                }

            order_no = match.group(0).upper()
            async with SessionLocal() as session, session.begin():
                service = OrderService(session)
                order = await service.get_order_for_user(order_no, state["user_id"])
            if not order:
                return {
                    "messages": [
                        AIMessage(content=f"没有找到订单 {order_no}，请核对订单号后重试。")
                    ]
                }

            shipment = order.get("shipment")
            answer = (
                f"订单 {order['order_no']} 当前状态：{order['status']}；"
                f"商品：{order['product_name']}；金额：¥{order['amount']:.2f}。"
            )
            if shipment:
                answer += (
                    f" 物流：{shipment['carrier']}，运单号 {shipment['tracking_no']}，"
                    f"{shipment['last_event']}。"
                )
            return {
                "messages": [AIMessage(content=answer)],
                "order_context": order,
                "citations": [],
            }

        graph = StateGraph(AgentState)
        graph.add_node("order_node", order_node)
        graph.add_edge(START, "order_node")
        graph.add_edge("order_node", END)
        return graph.compile()

    def _build_after_sales_subgraph(self):
        async def after_sales_node(state: AgentState) -> dict[str, Any]:
            user_text = self._latest_user_text(state)
            action_type = self._detect_action(user_text)
            order_match = ORDER_PATTERN.search(user_text)
            order_no = order_match.group(0).upper() if order_match else None
            requested_amount = self._extract_amount(user_text)
            approval_idempotency = hashlib.sha256(
                f"{state['session_id']}:{state['user_id']}:{action_type.value}:{user_text}".encode()
            ).hexdigest()
            payload = {
                "action_type": action_type.value,
                "order_no": order_no,
                "amount": requested_amount,
                "reason": user_text[:500],
            }

            async with SessionLocal() as session, session.begin():
                order_service = OrderService(session)
                order_info: dict[str, Any] | None = None
                validation_error: str | None = None

                if action_type in {
                    ActionType.REFUND,
                    ActionType.CANCEL_ORDER,
                    ActionType.COMPENSATION,
                }:
                    if not order_no:
                        validation_error = "请提供订单号，例如 ORD202600001，我再继续处理。"
                    else:
                        order_info = await order_service.get_order_for_user(
                            order_no, state["user_id"]
                        )
                        if order_info is None:
                            validation_error = (
                                f"订单 {order_no} 不存在，或不属于当前登录用户。"
                                "请核对订单号后再试。"
                            )

                if action_type == ActionType.REFUND and order_info:
                    amount = requested_amount or float(order_info["amount"])
                    if amount <= 0 or amount > float(order_info["amount"]):
                        validation_error = (
                            f"退款金额必须大于 0 且不能超过订单实付金额 "
                            f"¥{float(order_info['amount']):.2f}。"
                        )
                    payload["amount"] = amount

                if action_type == ActionType.COMPENSATION and order_info:
                    amount = requested_amount or 0
                    if amount <= 0 or amount > float(order_info["amount"]):
                        validation_error = "补偿金额必须大于 0 且不能超过订单实付金额。"
                    payload["amount"] = amount

                if validation_error:
                    await AuditService(session).record(
                        action="action_validation_failed",
                        resource_type="order",
                        resource_id=order_no,
                        actor_id=state["user_id"],
                        trace_id=state.get("trace_id"),
                        detail={"reason": validation_error, "payload": payload},
                    )
                    return {
                        "messages": [AIMessage(content=validation_error)],
                        "errors": [validation_error],
                        "approval": None,
                    }

                approval_service = ApprovalService(session)
                approval = await approval_service.create_pending(
                    session_id=state["session_id"],
                    user_id=state["user_id"],
                    action_type=action_type,
                    payload=payload,
                    idempotency_key=approval_idempotency,
                )
                await AuditService(session).record(
                    action="approval_requested",
                    resource_type="approval",
                    resource_id=approval.id,
                    actor_id=state["user_id"],
                    trace_id=state.get("trace_id"),
                    detail=payload,
                )
                approval_data = self._approval_payload(approval)

            decision = interrupt(
                {
                    "approval_id": approval_data["id"],
                    "action_type": action_type.value,
                    "payload": payload,
                    "message": "该操作涉及资金或订单变更，需要人工审批。",
                }
            )

            async with SessionLocal() as session, session.begin():
                approval_service = ApprovalService(session)
                approval = await approval_service.get(approval_data["id"])
                if approval is None:
                    raise RuntimeError("审批记录不存在")
                audit = AuditService(session)
                decision_value = str(decision.get("decision", "rejected"))

                if decision_value != ApprovalStatus.APPROVED.value:
                    feedback = "本次申请已被客服拒绝，订单和资金未发生变化。"
                    approval = await approval_service.mark_notified(approval)
                    await self._record_customer_feedback(
                        session,
                        state=state,
                        approval=approval,
                        content=feedback,
                        status="rejected",
                    )
                    await audit.record(
                        action="approval_rejected",
                        resource_type="approval",
                        resource_id=approval.id,
                        actor_id=decision.get("decided_by"),
                        trace_id=state.get("trace_id"),
                        detail={"comment": decision.get("comment")},
                    )
                    return {
                        "messages": [AIMessage(content=feedback)],
                        "approval": self._approval_payload(approval),
                    }

                if approval.status == ApprovalStatus.PENDING:
                    approval = await approval_service.decide(
                        approval.id,
                        decision=ApprovalStatus.APPROVED,
                        comment=decision.get("comment"),
                        version=approval.version,
                        decided_by=decision.get("decided_by") or "unknown-agent",
                    )

                order_service = OrderService(session)
                executed_payload = dict(payload)
                try:
                    if approval.action_type == ActionType.REFUND:
                        order_info = await order_service.get_order_for_user(
                            str(payload["order_no"]), state["user_id"]
                        )
                        if order_info is None:
                            raise ValueError("订单不存在或不属于当前用户")
                        refund_amount = float(payload.get("amount") or order_info["amount"])
                        if refund_amount > float(order_info["amount"]):
                            raise ValueError("退款金额超过订单实付金额")
                        executed_payload["amount"] = refund_amount
                        await order_service.create_refund(
                            order_no=str(payload["order_no"]),
                            user_id=state["user_id"],
                            amount=refund_amount,
                            reason=str(payload["reason"]),
                            approval_id=approval.id,
                            idempotency_key=approval.idempotency_key,
                        )
                        feedback = (
                            f"退款已处理成功，金额 ¥{refund_amount:.2f}，"
                            "通常会在三个工作日内原路退回。"
                        )
                        execution_result = {"refund_amount": refund_amount}
                    elif approval.action_type == ActionType.CANCEL_ORDER:
                        await order_service.cancel_order(
                            order_no=str(payload["order_no"]),
                            user_id=state["user_id"],
                        )
                        feedback = f"订单 {payload['order_no']} 已成功取消。"
                        execution_result = {"order_no": payload["order_no"], "status": "cancelled"}
                    elif approval.action_type == ActionType.COMPENSATION:
                        ticket = await order_service.create_ticket(
                            session_id=state["session_id"],
                            user_id=state["user_id"],
                            subject=f"补偿工单 {approval.id[:8]}",
                            description=str(payload["reason"]),
                            priority="high",
                        )
                        feedback = "补偿申请已通过并创建工单，客服会继续跟进。"
                        execution_result = {"ticket_id": ticket.id}
                    else:
                        ticket = await order_service.create_ticket(
                            session_id=state["session_id"],
                            user_id=state["user_id"],
                            subject=f"售后工单 {approval.id[:8]}",
                            description=str(payload["reason"]),
                        )
                        feedback = "售后工单已创建，客服会继续跟进。"
                        execution_result = {"ticket_id": ticket.id}

                    approval = await approval_service.mark_executed(approval, execution_result)
                    approval_status = "executed"
                except Exception as exc:
                    safe_error = self._safe_action_error(exc)
                    approval = await approval_service.mark_failed(approval, safe_error)
                    feedback = f"你的售后申请处理失败：{safe_error}。订单和资金未发生变化。"
                    approval_status = "failed"
                    execution_result = {"error": safe_error}

                approval = await approval_service.mark_notified(approval)
                await self._record_customer_feedback(
                    session,
                    state=state,
                    approval=approval,
                    content=feedback,
                    status=approval_status,
                )
                await audit.record(
                    action=f"approval_{approval_status}",
                    resource_type="approval",
                    resource_id=approval.id,
                    actor_id=decision.get("decided_by"),
                    trace_id=state.get("trace_id"),
                    detail=execution_result,
                )
                result = self._approval_payload(approval)

            return {
                "messages": [AIMessage(content=feedback)],
                "approval": result,
            }

        graph = StateGraph(AgentState)
        graph.add_node("after_sales_node", after_sales_node)
        graph.add_edge(START, "after_sales_node")
        graph.add_edge("after_sales_node", END)
        return graph.compile()

    @staticmethod
    def _safe_action_error(exc: Exception) -> str:
        message = str(exc).strip()
        if "不属于" in message or "不存在" in message:
            return "订单不存在或不属于当前用户"
        if "金额" in message:
            return message
        return "系统执行售后动作时发生异常"

    async def _record_customer_feedback(
        self,
        session,
        *,
        state: AgentState,
        approval: Approval,
        content: str,
        status: str,
    ) -> None:
        client_message_id = f"approval:{approval.id}:result"
        existing = await session.scalar(
            select(ChatMessage).where(
                ChatMessage.session_id == state["session_id"],
                ChatMessage.client_message_id == client_message_id,
            )
        )
        if existing is None:
            session.add(
                ChatMessage(
                    session_id=state["session_id"],
                    role="assistant",
                    content=content,
                    client_message_id=client_message_id,
                    event_metadata={
                        "approval_id": approval.id,
                        "approval_status": status,
                        "action_type": approval.action_type.value,
                    },
                )
            )

        notification_key = f"approval:{approval.id}:in_app"
        existing_notification = await session.scalar(
            select(Notification).where(Notification.idempotency_key == notification_key)
        )
        if existing_notification is None:
            session.add(
                Notification(
                    channel="in_app",
                    recipient=state["user_id"],
                    content=content,
                    status="sent",
                    attempts=1,
                    idempotency_key=notification_key,
                )
            )

    async def _response_node(self, state: AgentState) -> dict[str, Any]:
        if state.get("messages"):
            return {}
        return {"messages": [AIMessage(content="请求已处理。")]}

    @staticmethod
    def _latest_user_text(state: AgentState) -> str:
        for message in reversed(state.get("messages", [])):
            if isinstance(message, HumanMessage) or getattr(message, "type", "") == "human":
                content = message.content
                if isinstance(content, str):
                    return content
                return str(content)
        return ""

    @staticmethod
    def _heuristic_route(text: str) -> tuple[str, str, str]:
        lowered = text.lower()
        policy_question = any(
            keyword in text
            for keyword in ("政策", "规则", "条件", "多久", "多少", "是否可以", "能否", "怎么办")
        )
        high_risk_action = any(
            keyword in text
            for keyword in (
                "我要退款",
                "申请退款",
                "退钱",
                "补偿",
                "取消订单",
                "我要退货",
                "申请退货",
            )
        )
        if high_risk_action and not policy_question:
            return "after_sales", "after_sales_action", "high"
        if ORDER_PATTERN.search(text) or any(
            keyword in lowered for keyword in ("order", "订单", "物流", "快递")
        ):
            return "order", "order_status", "low"
        return "knowledge", "policy_question", "low"

    @staticmethod
    def _detect_action(text: str) -> ActionType:
        if "补偿" in text:
            return ActionType.COMPENSATION
        if "取消订单" in text:
            return ActionType.CANCEL_ORDER
        if "退款" in text or "退钱" in text:
            return ActionType.REFUND
        return ActionType.CREATE_TICKET

    @staticmethod
    def _extract_amount(text: str) -> float | None:
        patterns = (
            r"(?:退款|退钱|补偿|赔付|金额)\D{0,8}(\d+(?:\.\d{1,2})?)",
            r"(?:¥|￥|人民币)\s*(\d+(?:\.\d{1,2})?)",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return float(match.group(1))
        return None

    @staticmethod
    def _approval_payload(approval: Approval) -> dict[str, Any]:
        return {
            "id": approval.id,
            "session_id": approval.session_id,
            "user_id": approval.user_id,
            "action_type": approval.action_type.value,
            "payload": approval.payload,
            "status": approval.status.value,
            "version": approval.version,
            "error_message": approval.error_message,
            "result": approval.result,
            "notified_at": approval.notified_at,
            "idempotency_key": approval.idempotency_key,
        }

    def _langfuse_callbacks(self) -> list[Any]:
        if not (self.settings.langfuse_public_key and self.settings.langfuse_secret_key):
            return []
        try:
            os.environ.setdefault(
                "LANGFUSE_SECRET_KEY",
                self.settings.langfuse_secret_key.get_secret_value(),
            )
            os.environ.setdefault("LANGFUSE_HOST", self.settings.langfuse_host)
            from langfuse.langchain import CallbackHandler

            return [
                CallbackHandler(public_key=self.settings.langfuse_public_key.get_secret_value())
            ]
        except Exception as exc:
            logger.warning("langfuse_callback_init_failed: %s", exc)
            return []

    async def stream_chat(
        self,
        *,
        message: str,
        user_id: str,
        session_id: str,
        roles: list[str] | None = None,
        trace_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        state: AgentState = {
            "messages": [HumanMessage(content=message)],
            "user_id": user_id,
            "roles": roles or ["customer"],
            "session_id": session_id,
            "trace_id": trace_id or uuid.uuid4().hex,
            "errors": [],
        }
        async for event in self._stream_graph(state):
            yield event

    async def stream_resume(
        self,
        *,
        approval_id: str,
        decision: str,
        comment: str | None,
        decided_by: str,
        trace_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async with SessionLocal() as session:
            approval = await session.get(Approval, approval_id)
            if approval is None:
                raise LookupError("审批记录不存在")
            session_id = approval.session_id
        resume_value = {
            "approval_id": approval_id,
            "decision": decision,
            "comment": comment,
            "decided_by": decided_by,
            "trace_id": trace_id,
        }
        async for event in self._stream_graph(Command(resume=resume_value), session_id=session_id):
            yield event

    async def _stream_graph(
        self,
        graph_input: AgentState | Command,
        *,
        session_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if self.graph is None:
            await self.startup()
        assert self.graph is not None
        if session_id is None and isinstance(graph_input, dict):
            session_id = graph_input["session_id"]
        if not session_id:
            raise ValueError("session_id is required")

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 30,
            "callbacks": self._langfuse_callbacks(),
        }
        streamed_text = ""
        try:
            async for event in self.graph.astream_events(
                graph_input,
                config=config,
                version="v2",
            ):
                event_name = event.get("event")
                data = event.get("data", {})
                if event_name == "on_tool_start":
                    yield {
                        "event": "tool_call",
                        "data": {"phase": "start", "tool": event.get("name")},
                    }
                elif event_name == "on_tool_end":
                    yield {
                        "event": "tool_call",
                        "data": {"phase": "end", "tool": event.get("name")},
                    }
                elif event_name == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    content = getattr(chunk, "content", "")
                    if isinstance(content, str) and content:
                        streamed_text += content
                        yield {"event": "token", "data": {"content": content}}

            snapshot = await self.graph.aget_state(config)
            interrupts = [
                interrupt_record.value
                for task in snapshot.tasks
                for interrupt_record in task.interrupts
            ]
            if interrupts:
                for value in interrupts:
                    yield {"event": "approval_required", "data": value}
                return

            state_values = snapshot.values or {}
            messages: list[BaseMessage] = state_values.get("messages", [])
            final_text = ""
            if messages:
                content = messages[-1].content
                final_text = content if isinstance(content, str) else str(content)
            if final_text and final_text not in streamed_text:
                yield {"event": "token", "data": {"content": final_text}}

            for citation in state_values.get("citations", []):
                yield {"event": "citation", "data": citation}
            yield {
                "event": "done",
                "data": {
                    "session_id": session_id,
                    "route": state_values.get("route"),
                    "approval": state_values.get("approval"),
                },
            }
        except Exception as exc:
            logger.exception("agent_stream_failed")
            yield {"event": "error", "data": {"message": str(exc)}}
