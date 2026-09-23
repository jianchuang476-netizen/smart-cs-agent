from fastapi.testclient import TestClient

from app.main import app


def test_health_and_login_flow():
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200

        response = client.post(
            "/api/v1/auth/login",
            json={"email": "customer@example.com", "password": "Demo123!"},
        )
        assert response.status_code == 200
        assert "smart_cs_access" in response.cookies

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["role"] == "customer"

        forbidden = client.get("/api/v1/approvals")
        assert forbidden.status_code == 403
