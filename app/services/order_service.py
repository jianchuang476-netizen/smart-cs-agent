from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import mask_phone, mask_pii
from app.db.models import Order, RefundRequest, Shipment, SupportTicket


class OrderService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_order_for_user(self, order_no: str, user_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(
            select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
        )
        order = result.scalar_one_or_none()
        if order is None:
            return None

        shipment_result = await self.session.execute(
            select(Shipment).where(Shipment.order_id == order.id)
        )
        shipment = shipment_result.scalar_one_or_none()
        return {
            "order_no": order.order_no,
            "product_name": order.product_name,
            "status": order.status,
            "amount": order.amount,
            "purchased_at": order.purchased_at.isoformat(),
            "return_deadline": order.return_deadline.isoformat(),
            "contact_phone": mask_phone(order.contact_phone),
            "shipping_address": mask_pii(order.shipping_address),
            "shipment": (
                {
                    "carrier": shipment.carrier,
                    "tracking_no": shipment.tracking_no,
                    "status": shipment.status,
                    "last_event": shipment.last_event,
                    "estimated_delivery": (
                        shipment.estimated_delivery.isoformat()
                        if shipment.estimated_delivery
                        else None
                    ),
                }
                if shipment
                else None
            ),
        }

    async def create_refund(
        self,
        *,
        order_no: str,
        user_id: str,
        amount: float,
        reason: str,
        approval_id: str,
        idempotency_key: str,
    ) -> RefundRequest:
        existing = await self.session.scalar(
            select(RefundRequest).where(RefundRequest.idempotency_key == idempotency_key)
        )
        if existing:
            return existing

        order = await self.session.scalar(
            select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
        )
        if order is None:
            raise ValueError("订单不存在或不属于当前用户")
        if amount <= 0 or amount > order.amount:
            raise ValueError("退款金额不合法")

        refund = RefundRequest(
            order_id=order.id,
            user_id=user_id,
            approval_id=approval_id,
            amount=amount,
            reason=reason,
            status="approved",
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.session.add(refund)
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            existing = await self.session.scalar(
                select(RefundRequest).where(RefundRequest.idempotency_key == idempotency_key)
            )
            if existing is None:
                raise
            return existing
        return refund

    async def cancel_order(self, *, order_no: str, user_id: str) -> Order:
        order = await self.session.scalar(
            select(Order).where(Order.order_no == order_no, Order.user_id == user_id)
        )
        if order is None:
            raise ValueError("订单不存在或不属于当前用户")
        order.status = "已取消"
        await self.session.flush()
        return order

    async def create_ticket(
        self,
        *,
        session_id: str,
        user_id: str,
        subject: str,
        description: str,
        priority: str = "normal",
    ) -> SupportTicket:
        ticket = SupportTicket(
            session_id=session_id,
            user_id=user_id,
            subject=subject[:255],
            description=description,
            priority=priority,
        )
        self.session.add(ticket)
        await self.session.flush()
        return ticket
