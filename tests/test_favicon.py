from fastapi.testclient import TestClient
from app.main import app


def test_favicon_served():
    r = TestClient(app).get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
