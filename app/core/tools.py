"""Agent 可调用的业务工具。"""


def query_order(order_id: str) -> dict:
    """查询订单信息。实际实现应委托给 services.mysql_db。"""
    # TODO: 接入 MySQL 订单查询。
    return {"order_id": order_id, "status": "unknown"}


def send_dingtalk_notification(content: str) -> dict:
    """发送钉钉通知。"""
    # TODO: 接入钉钉机器人 Webhook。
    return {"sent": False, "content": content}
