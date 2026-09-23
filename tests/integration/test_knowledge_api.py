from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_admin_can_upload_list_and_delete_document(monkeypatch):
    monkeypatch.setattr(
        "app.worker.tasks.ingest_document.delay",
        lambda *args, **kwargs: None,
    )
    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"email": "admin@example.com", "password": "Demo123!"},
        )
        assert login.status_code == 200
        csrf = client.cookies.get("smart_cs_csrf")
        response = client.post(
            "/api/v1/knowledge/documents",
            files={"file": ("extra_policy.md", b"# Extra policy\n\nTest content", "text/markdown")},
            data={"title": "额外政策", "version": "1.0"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 200
        document_id = response.json()["id"]

        documents = client.get("/api/v1/knowledge/documents")
        assert documents.status_code == 200
        assert any(item["id"] == document_id for item in documents.json())

        deleted = client.delete(
            f"/api/v1/knowledge/documents/{document_id}",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 204
