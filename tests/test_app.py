import io, pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.depth import estimate, band_for, passability
from app.providers import get_providers
from app.providers.base import Mask, Segmentation
from app.providers.mock import MockVision
from scripts import seed


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "t.db"; seed.main(db)
    return TestClient(create_app(db_path=db, provider="mock"))


def test_bands():
    assert band_for(0) == "none" and band_for(10) == "ankle" and band_for(40) == "knee"
    assert band_for(90) == "waist" and band_for(150) == "chest"
    assert passability(10) == "all" and passability(40) == "trucks" and passability(80) == "boats"


def test_estimate_half_submerged_person():
    seg = Segmentation([Mask("person", (0.4, 0.2, 0.6, 1.0), 0.9), Mask("water", (0, 0.6, 1, 1), 0.9)])
    assert estimate(seg)["depth_cm"] == 80


def test_mock_is_deterministic():
    v = MockVision(); a = v.segment(b"photo", ["water", "person"]); b = v.segment(b"photo", ["water", "person"])
    assert a == b


def test_meta_stub_raises():
    v, r = get_providers("meta")
    with pytest.raises(NotImplementedError): v.segment(b"x", ["water"])
    with pytest.raises(NotImplementedError): r.situation_report({}, "en")


def test_seeded_and_summary(client):
    rs = client.get("/api/reports").json(); assert len(rs) == 10 and all(r["simulated"] for r in rs)
    s = client.get("/api/summary/Tumana").json()
    assert s["streets"][0]["street"] == "Bayabas St" and s["streets"][0]["passability"] == "boats"
    assert s["streets"][0]["people_at_risk"]


def test_upload_and_sitrep(client):
    r = client.post("/api/reports", data={"lat": 14.65, "lng": 121.1, "barangay": "Tumana", "street": "Test St", "note": "help"},
                    files={"photo": ("a.jpg", io.BytesIO(b"fake-image-bytes"), "image/jpeg")})
    assert r.status_code == 201 and r.json()["band"] in {"none", "ankle", "knee", "waist", "chest"}
    sr = client.get("/api/sitrep/Tumana").json()
    assert "Bayabas St" in sr["en"] and "Barangay Tumana" in sr["fil"] and "hanggang" in sr["fil"]


def test_bad_coords(client):
    r = client.post("/api/reports", data={"lat": 200, "lng": 0, "barangay": "X", "street": "Y"},
                    files={"photo": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 422


def test_meta_provider_returns_501(tmp_path):
    c = TestClient(create_app(db_path=tmp_path / "m.db", provider="meta"))
    r = c.post("/api/reports", data={"lat": 1, "lng": 1, "barangay": "X", "street": "Y"}, files={"photo": ("a.jpg", b"x", "image/jpeg")})
    assert r.status_code == 501
