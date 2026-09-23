from fastapi import APIRouter

from app.api.v1 import approvals, auth, chat, knowledge, sessions

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(chat.router)
api_router.include_router(sessions.router)
api_router.include_router(approvals.router)
api_router.include_router(knowledge.router)
