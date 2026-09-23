from __future__ import annotations

import pytest

from app.config import Settings
from app.db.session import SessionLocal
from app.services.notification import (
    MockNotificationAdapter,
    NotificationService,
    build_notification_adapter,
)


async def test_mock_notification_is_idempotent():
    async with SessionLocal() as session:
        service = NotificationService(session, adapter=MockNotificationAdapter())
        first = await service.send(
            content="测试通知",
            idempotency_key="unit:notification:1",
            recipient="user-1",
            channel="in_app",
        )
        second = await service.send(
            content="测试通知",
            idempotency_key="unit:notification:1",
            recipient="user-1",
            channel="in_app",
        )
        assert first.id == second.id
        assert first.status == "sent"
        assert first.attempts == 1
        await session.commit()


def test_notification_adapter_factory_requires_dingtalk_webhook():
    assert isinstance(
        build_notification_adapter(Settings(notification_provider="mock")),
        MockNotificationAdapter,
    )
    with pytest.raises(RuntimeError):
        build_notification_adapter(Settings(notification_provider="dingtalk"))
