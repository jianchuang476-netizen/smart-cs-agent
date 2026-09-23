from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.config import PROJECT_ROOT, get_settings
from app.core.security import hash_password
from app.db.models import KnowledgeDocument, Order, Shipment, User, UserRole
from app.db.session import SessionLocal, init_db
from app.services.rag_service import KnowledgeIngestor

DEMO_PASSWORD = "Demo123!"
CUSTOMER_COUNT = 20
ORDER_COUNT = 100
PRODUCTS = [
    "智能路由器 Pro",
    "无线降噪耳机",
    "便携充电宝",
    "智能手表",
    "机械键盘",
    "高清摄像头",
    "智能音箱",
    "蓝牙鼠标",
    "桌面显示器",
    "USB-C 扩展坞",
]
ORDER_STATUSES = ["已支付", "已发货", "运输中", "已签收", "已完成", "已取消"]
CARRIERS = ["顺丰速运", "中通快递", "圆通速递", "京东物流"]


def _customer_email(index: int) -> str:
    if index == 0:
        return "customer@example.com"
    return f"customer{index + 3}@example.com"


async def _seed_users(session) -> list[User]:
    result = await session.execute(select(User))
    users = {user.email: user for user in result.scalars().all()}

    demo_users = [
        ("customer@example.com", "演示客户", UserRole.CUSTOMER),
        ("agent@example.com", "客服小王", UserRole.AGENT),
        ("admin@example.com", "系统管理员", UserRole.ADMIN),
    ]
    for email, display_name, role in demo_users:
        if email not in users:
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name=display_name,
                role=role,
            )
            session.add(user)
            users[email] = user

    for index in range(1, CUSTOMER_COUNT):
        email = _customer_email(index)
        if email not in users:
            user = User(
                email=email,
                password_hash=hash_password(DEMO_PASSWORD),
                display_name=f"客户 {index + 1}",
                role=UserRole.CUSTOMER,
            )
            session.add(user)
            users[email] = user

    await session.flush()
    return [users[_customer_email(index)] for index in range(CUSTOMER_COUNT)]


async def _seed_orders(session, customers: list[User]) -> list[Order]:
    result = await session.execute(select(Order))
    existing_orders = {order.order_no: order for order in result.scalars().all()}
    now = datetime.now(UTC)
    orders: list[Order] = []

    for index in range(1, ORDER_COUNT + 1):
        order_no = f"ORD202600{index:03d}"
        customer = customers[(index - 1) % CUSTOMER_COUNT]
        purchased_at = now - timedelta(days=index % 120, hours=index % 24)
        amount = round(59 + (index % 20) * 19.9 + index * 3.7, 2)
        status = ORDER_STATUSES[(index - 1) % len(ORDER_STATUSES)]
        order = existing_orders.get(order_no) or Order(order_no=order_no)
        order.user_id = customer.id
        order.product_name = PRODUCTS[(index - 1) % len(PRODUCTS)]
        order.status = status
        order.amount = amount
        order.purchased_at = purchased_at
        order.return_deadline = purchased_at + timedelta(days=15)
        order.contact_phone = f"138{(10000000 + index * 7919) % 100000000:08d}"
        order.shipping_address = (
            f"上海市浦东新区演示路{(index - 1) % 50 + 1}号{index % 8 + 1}单元{index % 20 + 1}室"
        )
        if order_no not in existing_orders:
            session.add(order)
        orders.append(order)

    await session.flush()
    return orders


async def _seed_shipments(session, orders: list[Order]) -> None:
    result = await session.execute(select(Shipment))
    shipments = {shipment.order_id: shipment for shipment in result.scalars().all()}
    now = datetime.now(UTC)

    for index, order in enumerate(orders, start=1):
        if order.status == "已取消":
            continue
        shipment = shipments.get(order.id) or Shipment(order_id=order.id)
        shipment.carrier = CARRIERS[(index - 1) % len(CARRIERS)]
        shipment.tracking_no = f"TRK{index:012d}"
        shipment.status = "已签收" if order.status in {"已签收", "已完成"} else "运输中"
        shipment.last_event = (
            "快件已签收，感谢使用"
            if shipment.status == "已签收"
            else f"快件已到达{order.shipping_address[:8]}集散中心"
        )
        shipment.estimated_delivery = now + timedelta(days=index % 5)
        if order.id not in shipments:
            session.add(shipment)


async def _seed_documents(session) -> list[KnowledgeDocument]:
    result = await session.execute(select(KnowledgeDocument))
    existing = {document.content_hash: document for document in result.scalars().all()}
    documents: list[KnowledgeDocument] = []
    docs_dir = PROJECT_ROOT / "data" / "docs"
    for path in sorted(docs_dir.glob("*.md")):
        content_hash = KnowledgeIngestor.content_hash(path)
        document = existing.get(content_hash)
        if document is None:
            document = KnowledgeDocument(
                title=path.stem,
                filename=path.name,
                version="1.0",
                source_uri=str(path),
                content_hash=content_hash,
                status="pending",
                metadata_json={"seed": True},
            )
            session.add(document)
            existing[content_hash] = document
        documents.append(document)
    await session.flush()
    return documents


async def seed_database(*, ingest_documents: bool = False) -> dict[str, int]:
    await init_db()
    async with SessionLocal() as session:
        customers = await _seed_users(session)
        orders = await _seed_orders(session, customers)
        await _seed_shipments(session, orders)
        documents = await _seed_documents(session)
        await session.commit()

        if ingest_documents:
            ingestor = KnowledgeIngestor(get_settings())
            for document in documents:
                path = Path(document.source_uri or "")
                count = await ingestor.ingest_path(
                    document_id=document.id,
                    path=path,
                    title=document.title,
                    source_uri=str(path),
                    version=document.version,
                )
                document.chunk_count = count
                document.status = "active"
            await session.commit()

        return {
            "users": len(customers) + 2,
            "orders": len(orders),
            "documents": len(documents),
        }


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(seed_database(ingest_documents=False))
    print(result)
