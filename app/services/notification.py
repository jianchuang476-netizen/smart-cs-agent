from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db.models import Notification


class NotificationAdapter(ABC):
    @abstractmethod
    async def send(self, content: str, recipient: str | None = None) -> dict[str, Any]:
        raise NotImplementedError


class MockNotificationAdapter(NotificationAdapter):
    async def send(self, content: str, recipient: str | None = None) -> dict[str, Any]:
        return {"ok": True, "provider": "mock", "recipient": recipient, "content": content}


class DingTalkNotificationAdapter(NotificationAdapter):
    def __init__(self, webhook: str) -> None:
        self.webhook = webhook

    async def send(self, content: str, recipient: str | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.webhook,
                json={"msgtype": "text", "text": {"content": content}},
            )
            response.raise_for_status()
            return response.json()


def build_notification_adapter(settings: Settings | None = None) -> NotificationAdapter:
    settings = settings or get_settings()
    if settings.notification_provider == "dingtalk":
        if settings.dingtalk_webhook is None:
            raise RuntimeError("DINGTALK_WEBHOOK 未配置")
        return DingTalkNotificationAdapter(settings.dingtalk_webhook.get_secret_value())
    return MockNotificationAdapter()


class NotificationService:
    def __init__(
        self,
        session: AsyncSession,
        adapter: NotificationAdapter | None = None,
    ) -> None:
        self.session = session
        self.adapter = adapter or build_notification_adapter()

    async def send(
        self,
        *,
        content: str,
        idempotency_key: str,
        recipient: str | None = None,
        channel: str = "dingtalk",
    ) -> Notification:
        existing = await self.session.scalar(
            select(Notification).where(Notification.idempotency_key == idempotency_key)
        )
        if existing and existing.status == "sent":
            return existing

        record = existing or Notification(
            channel=channel,
            recipient=recipient,
            content=content,
            status="pending",
            idempotency_key=idempotency_key,
        )
        if existing is None:
            self.session.add(record)
            await self.session.flush()

        record.attempts += 1
        try:
            await self.adapter.send(content, recipient)
            record.status = "sent"
            record.last_error = None
        except Exception as exc:
            record.status = "failed"
            record.last_error = str(exc)[:1000]
        await self.session.flush()
        return record
