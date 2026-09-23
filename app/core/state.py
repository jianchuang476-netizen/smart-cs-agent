from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    roles: list[str]
    session_id: str
    intent: str
    route: Literal["knowledge", "order", "after_sales", "respond"]
    retrieved_docs: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    order_context: dict[str, Any] | None
    pending_action: dict[str, Any] | None
    approval: dict[str, Any] | None
    risk_level: Literal["low", "high"]
    ticket: dict[str, Any] | None
    errors: list[str]
    trace_id: str
