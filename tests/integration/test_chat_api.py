from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


class FakeAgent:
    async def stream_chat(self, **kwargs):
        yield {"event": "token", "data": {"content": "政策答案"}}
        yield {"event": "done", "data": {"session_id": kwargs["session_id"]}}


def test_chat_stream_persists_messages():
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": "Demo123!"},
        )
        assert login.status_code == 200
        csrf = client.cookies.get("smart_cs_csrf")
        app.state.agent = FakeAgent()

        response = client.post(
            "/api/v1/chat/stream",
            json={"message": "退货政策是什么？", "client_message_id": "test-message-1"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        assert "event: token" in response.text
        assert "政策答案" in response.text

        sessions = client.get("/api/v1/sessions").json()
        assert sessions
        messages = client.get(f"/api/v1/sessions/{sessions[0]['id']}/messages").json()
        assert messages[-1]["content"] == "政策答案"
