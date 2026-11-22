from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_landing_and_workspace_pages_served() -> None:
    landing = client.get("/")
    assert landing.status_code == 200
    assert "text/html" in landing.headers["content-type"]
    assert "реальную цену подрядчика" in landing.text

    workspace = client.get("/workspace")
    assert workspace.status_code == 200
    assert "text/html" in workspace.headers["content-type"]
    assert "Сравнение предложений под ваш заказ" in workspace.text


def test_frontend_static_assets_served() -> None:
    for asset in ("styles.css", "theme.js", "motion.js", "api.js", "render.js", "workspace.js"):
        resp = client.get(f"/static/{asset}")
        assert resp.status_code == 200
