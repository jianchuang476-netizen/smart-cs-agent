from __future__ import annotations

from collections.abc import Callable

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.models import User, UserRole
from app.db.session import get_db

ACCESS_COOKIE = "smart_cs_access"
REFRESH_COOKIE = "smart_cs_refresh"
CSRF_COOKIE = "smart_cs_csrf"


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> User:
    authorization = request.headers.get("Authorization", "")
    token = ""
    if authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    if not token:
        token = request.cookies.get(ACCESS_COOKIE, "")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未登录")
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态无效或已过期"
        ) from exc

    user = await session.get(User, str(payload.get("sub")))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不可用")
    return user


def require_roles(*roles: UserRole) -> Callable:
    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return dependency


async def verify_csrf(request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    if authorization.startswith("Bearer "):
        return
    cookie_token = request.cookies.get(CSRF_COOKIE)
    header_token = request.headers.get("X-CSRF-Token")
    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF 校验失败")


async def rate_limit(request: Request, user: User = Depends(get_current_user)) -> None:
    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        return
    settings = request.app.state.settings
    key = f"rate:{user.id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, settings.rate_limit_window_seconds)
    if count > settings.rate_limit_requests:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="请求过于频繁，请稍后重试",
        )
