from app.core.security import verify_admin_access
from app.routes.public_knowledge import admin_router, router
from app.services.public_knowledge_service import PublicKnowledgeService
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.services.test_public_knowledge_service import PAGE


def test_publication_requires_admin_and_exact_preview(tmp_path):
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "guide.md").write_text(PAGE)
    service = PublicKnowledgeService(pages, tmp_path / "knowledge.db")
    app = FastAPI()
    app.state.public_knowledge_service = service
    app.include_router(router)
    app.include_router(admin_router)
    with TestClient(app) as client:
        public_url = "/public/knowledge/synthetic-guide"
        admin_url = "/admin/knowledge-updates/pages/synthetic-guide"
        assert client.get(public_url).status_code == 404
        assert client.get(admin_url).status_code in {401, 403}
        assert client.post(
            admin_url + "/publish", json={"revision": "a" * 64, "reviewer": "admin"}
        ).status_code in {401, 403}
        app.dependency_overrides[verify_admin_access] = lambda: True
        preview = client.get(admin_url).json()
        assert "PRIVATE" in preview["body"]
        assert (
            client.post(
                admin_url + "/publish", json={"revision": "a" * 64, "reviewer": "admin"}
            ).status_code
            == 409
        )
        assert (
            client.post(
                admin_url + "/publish",
                json={
                    "revision": preview["projection"]["revision"],
                    "reviewer": "admin",
                },
            ).status_code
            == 200
        )
        public = client.get(public_url)
        assert public.status_code == 200
        assert public.headers["cache-control"] == "no-store"
        assert "PRIVATE" not in public.text
        assert "publication_history" not in public.json()
        assert (
            client.post(admin_url + "/revoke", json={"reviewer": "admin"}).status_code
            == 200
        )
        assert client.get(public_url).status_code == 404
