import math
from datetime import datetime, timedelta, timezone
from app import cells, assess, db
from scripts import seed
from tests.test_app import client, find_photo, post  # noqa: F401

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def r(i, mins_ago, lat=14.6500, lng=121.0950, cid=None, conf=0.9, band="knee", src="gps", kind="flood"):
    return {"id": i, "reported_at": (NOW - timedelta(minutes=mins_ago)).isoformat(), "lat": lat, "lng": lng, "barangay": "X",
            "street": "A St", "band": band, "confidence": conf, "depth_cm": 40, "water_level": None, "client_id": cid,
            "loc_source": src, "kind": kind, "people_at_risk": False, "assessment": {}, "status": "ok", "simulated": False}


def test_cell_snapping_is_about_250m():
    (a, b) = cells.bounds(*cells.cell_of(14.65, 121.095))
    h = (b[0] - a[0]) * 111320; w = (b[1] - a[1]) * 111320 * math.cos(math.radians(14.65))
    assert 249 < h < 251 and 249 < w < 251
    assert cells.cell_of(14.65, 121.095) != cells.cell_of(14.65, 121.100)       # ~540 m apart: different cells


def test_decay_half_life_and_expiry():
    assert cells.weight(0) == 1 and abs(cells.weight(cells.HALF_LIFE_MIN) - 0.5) < 1e-9
    assert cells.weight(cells.EXPIRE_H * 60 + 1) == 0
    out = cells.build([r(1, cells.EXPIRE_H * 60 + 5)], NOW)
    assert out == []                                                               # expired: no cell at all


def test_states_observed_unconfirmed_stale():
    one = cells.build([r(1, 5)], NOW)[0]
    assert one["state"] == "unconfirmed" and one["independent_reporters"] == 1
    two = cells.build([r(1, 5, cid="a"), r(2, 10, cid="b", lat=14.6501)], NOW)[0]
    assert two["state"] == "observed" and two["confidence"] > one["confidence"]
    old = cells.build([r(1, 150, cid="a"), r(2, 160, cid="b")], NOW)[0]
    assert old["state"] == "stale" and old["last_observed_min_ago"] == 150
    assert "points" not in two                                                     # public view: no exact points
    resp = cells.build([r(1, 5)], NOW, responder=True)[0]
    assert resp["points"][0]["lat"] == 14.65


def test_same_device_counts_once():
    same = cells.build([r(1, 5, cid="a"), r(2, 6, cid="a"), r(3, 7, cid="a")], NOW)[0]
    assert same["reports"] == 3 and same["independent_reporters"] == 1 and same["state"] == "unconfirmed"
    # incident ladder dedupes too: 3 reports from one device are not corroboration
    rs = [r(i, 5 + i, cid="a") | {"water_level": "knee", "note": ""} for i in (1, 2, 3)]
    a = assess.assess_incident(rs, {}, [], NOW)
    assert a["independent_reporters"] == 1 and a["ladder"] in ("user_reported", "ai_grouped")


def test_community_and_responder_confirm():
    c = cells.build([r(1, 5)], NOW, votes_by_report={1: {"still": 1}})[0]
    assert c["state"] == "observed"
    v = cells.build([r(1, 5, src="barangay", conf=0.6)], NOW, confirmed_reports={1})[0]
    assert v["confidence"] >= 0.9 and v["state"] == "observed"


def test_cells_api_on_seed(client):
    m = client.get("/api/cells").json()
    assert m["cell_m"] == 250 and m["cells"]
    states = {c["state"] for c in m["cells"]}
    assert "observed" in states and ("unconfirmed" in states or "stale" in states)
    for c in m["cells"]:
        assert "points" not in c and {"last_observed_min_ago", "confidence", "bounds"} <= set(c)
    mal = client.get("/api/cells", params={"barangay": "Malanday"}).json()["cells"]
    assert mal and all("Malanday" in c["barangays"] for c in mal)
    assert client.get("/api/cells", params={"view": "responder"}).json()["cells"][0]["points"]
    assert client.get("/api/area/Malanday").json()["status"] == "danger"           # seed #9 still drives Danger
    # same client posting twice in one spot = one independent reporter
    for _ in range(2):
        assert post(client, find_photo(False), lat=14.6400, lng=121.0800, client_id="dev-1").status_code == 201
    c = [c for c in client.get("/api/cells").json()["cells"] if "Test St" in c["streets"]][0]
    assert c["reports"] == 2 and c["independent_reporters"] == 1
    assert "client_id" not in str(client.get("/api/incidents?view=responder").json())


def test_demo_clock_keeps_seed_live(tmp_path):
    p = tmp_path / "d.db"; seed.main(p, now=datetime.now(timezone.utc) - timedelta(hours=10))
    from fastapi.testclient import TestClient
    from app.main import create_app
    c = TestClient(create_app(db_path=p, provider="mock"))
    assert c.get("/api/area/Malanday").json()["status"] == "danger"
    assert any(x["state"] == "observed" for x in c.get("/api/cells").json()["cells"])
