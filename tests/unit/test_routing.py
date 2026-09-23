import pytest

from app.core.agent import AgentRuntime


@pytest.mark.parametrize(
    ("text", "expected_route", "expected_risk"),
    [
        ("七天无理由退货政策是什么？", "knowledge", "low"),
        ("帮我查 ORD202600001 的物流", "order", "low"),
        ("订单 ORD202600002 我要退款 99 元", "after_sales", "high"),
        ("我要投诉并申请补偿", "after_sales", "high"),
    ],
)
def test_heuristic_routing(text, expected_route, expected_risk):
    route, _intent, risk = AgentRuntime._heuristic_route(text)
    assert route == expected_route
    assert risk == expected_risk
