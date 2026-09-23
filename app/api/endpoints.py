from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["agent"])


class ChatRequest(BaseModel):
    message: str
    session_id: str


class ApprovalRequest(BaseModel):
    session_id: str
    approved: bool
    comment: str | None = None


@router.post("/chat")
async def chat(payload: ChatRequest) -> dict:
    """接收用户消息并交给 LangGraph Agent 处理。"""
    # TODO: 调用 app.core.agent.run_agent(payload.message, payload.session_id)
    return {
        "session_id": payload.session_id,
        "message": "Agent 服务已就绪，等待接入 LangGraph 核心逻辑。",
    }


@router.post("/approve")
async def approve(payload: ApprovalRequest) -> dict:
    """处理需要人工确认的操作。"""
    # TODO: 调用 app.core.agent.resume_agent(...)
    return {
        "session_id": payload.session_id,
        "approved": payload.approved,
        "comment": payload.comment,
    }
