"""MySQL 订单查询服务。"""


class MySQLOrderRepository:
    def __init__(self, host: str, port: int, user: str, password: str, database: str) -> None:
        self.config = {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "database": database,
        }

    def get_order(self, order_id: str) -> dict | None:
        """按订单号查询订单。"""
        raise NotImplementedError("请接入 mysql-connector-python 并实现查询。")
