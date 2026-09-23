from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.config import get_settings

password_hasher = PasswordHasher()
PHONE_PATTERN = re.compile(r"(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)")
ADDRESS_PATTERN = re.compile(r"(地址[:：]?\s*)([^\n，,]{6,})")


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except VerifyMismatchError:
        return False


def create_token(
    subject: str,
    *,
    token_type: str,
    roles: list[str] | None = None,
    expires_delta: timedelta,
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": secrets.token_urlsafe(12),
        "roles": roles or [],
    }
    return cast(
        str,
        jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        ),
    )


def decode_token(token: str, expected_type: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("Unexpected token type")
    return payload


def create_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def mask_phone(value: str) -> str:
    return PHONE_PATTERN.sub(lambda match: f"{match.group(1)}****{match.group(3)}", value)


def mask_address(value: str) -> str:
    return ADDRESS_PATTERN.sub(lambda match: f"{match.group(1)}{match.group(2)[:3]}***", value)


def mask_pii(value: str) -> str:
    return mask_address(mask_phone(value))


def sanitize_retrieved_text(text: str, max_length: int = 4000) -> str:
    cleaned = text.replace("\x00", " ").strip()
    blocked_markers = (
        "ignore previous instructions",
        "忽略之前的指令",
        "system prompt",
        "developer message",
    )
    for marker in blocked_markers:
        cleaned = cleaned.replace(marker, "[已过滤内容]")
    return cleaned[:max_length]
