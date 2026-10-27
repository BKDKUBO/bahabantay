import io, json, pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import create_app
from app.depth import estimate, band_for, passability, from_answer, MIN_CONFIDENCE
from app.aggregate import trend
from app.agent import Tools, detect_lang
from app.providers import get_providers
from app.providers.base import Mask, Segmentation
from app.providers.mock import MockVision, MockAgent
from scripts import seed, eval_depth


@pytest.fixture
def client(tmp_path):
    db = tmp_path / "t.db"; seed.main(db)
    return TestClient(create_app(db_path=db, provider="mock"))


def find_photo(want_cant_tell: bool):
    v = MockVision()
    for i in range(500):
        b = f"photo-{i}".encode(); e = estimate(v.segment(b, ["water", "person", "door"]))
        if (e["band"] == "cant_tell") == want_cant_tell: return b
    raise AssertionError


def post(client, photo, **kw):
    data = {"lat": 14.65, "lng": 121.1, "barangay": "Tumana", "street": "Test St", "note": "", **kw}
    return client.post("/api/reports", data=data, files={"photo": ("a.jpg", io.BytesIO(photo), "image/jpeg")})


# --- depth / can't tell
def test_bands():
    assert band_for(0) == "none" and band_for(10) == "ankle" and band_for(40) == "knee"
    assert band_for(90) == "waist" and band_for(150) == "chest" and band_for(None) == "cant_tell"
    assert passability(10) == "all" and passability(40) == "trucks" and passability(80) == "boats"


def test_estimate_half_submerged_person():
    seg = Segmentation([Mask("person", (0.4, 0.2, 0.6, 1.0), 0.9), Mask("water", (0, 0.6, 1, 1), 0.9)])
    assert estimate(seg)["depth_cm"] == 80


def test_cant_tell_no_reference_and_low_conf():
    assert estimate(Segmentation([Mask("water", (0, .5, 1, 1), .9)]))["reason"] == "no_reference"
    low = estimate(Segmentation([Mask("door", (0, .2, 1, 1), MIN_CONFIDENCE - .1), Mask("water", (0, .5, 1, 1), .9)]))
    assert low["band"] == "cant_tell" and low["depth_cm"] is None and low["reason"] == "low_confidence"


def test_from_answer():
    assert from_answer("door", 50)["depth_cm"] == 105
    with pytest.raises(ValueError): from_answer("tree", 50)


def test_mock_is_deterministic():
    v = MockVision(); assert v.segment(b"p", ["water", "person"]) == v.segment(b"p", ["water", "person"])


def test_meta_constructs_and_has_name():
    v, r, a = get_providers("meta")
    assert v.name == "meta" and r.name == "meta" and a.name == "meta"


def test_parse_sam_boxes():
    from app.providers.meta import parse_sam_output_text
    sample = (
        "<0f>0<|box;x1=353;y1=382;x2=453;y2=427;w=537;h=561;c=0.9|>"
        "<|mask;x=0;y=0;data=46,101,~...|>,"
        "1<|box;x1=260;y1=382;x2=340;y2=427;w=537;h=561|>"
        "<|mask;x=0;y=0;data=46,81,~...|>"
    )
    masks = parse_sam_output_text(sample, "person")
    assert len(masks) == 2
    assert masks[0].label == "person"
    assert masks[0].bbox == pytest.approx((353 / 537, 382 / 561, 453 / 537, 427 / 561))
    assert masks[0].score == pytest.approx(0.9)
    assert masks[1].score == pytest.approx(0.85)  # default when c absent
    assert parse_sam_output_text("", "water") == []


# --- agent tools
def test_detect_lang():
    assert detect_lang("Baha na dito") == "fil" and detect_lang("water rising fast") == "en"


def test_tools_nearby_duplicates_risk():
    t0 = datetime(2026, 10, 26, tzinfo=timezone.utc)
    mk = lambda i, lat, mins, street="A", note="": {"id": i, "lat": lat, "lng": 121.0, "street": street, "note": note,
                                                    "reported_at": (t0 + timedelta(minutes=mins)).isoformat(), "duplicate_of": None}
    rs = [mk(1, 14.0, 0), mk(2, 14.0001, 5), mk(3, 14.0001, 90), mk(4, 14.01, 0)]
    tools = Tools(rs); new = mk(5, 14.0001, 10, note="May matanda, tulong!")
    near = tools.get_nearby_reports(new, 100)
    assert {r["id"] for r in near} == {1, 2, 3}
    assert tools.merge_duplicates(new, near) == 1
    assert tools.flag_people_at_risk(new) and not tools.flag_people_at_risk(mk(6, 14, 0, note="ok"))
    assert "pinto" in tools.ask_followup({"lang": "fil", "reason": "no_reference"})
    assert "door" in tools.ask_followup({"lang": "en", "reason": "no_reference"})


# --- trend
def test_trend():
    t0 = datetime(2026, 10, 26)
    up = [(t0 + timedelta(hours=h), 20 + 30 * h) for h in range(3)]
    assert trend(up) == ("rising", 30.0)
    assert trend([(t0, 80), (t0 + timedelta(hours=2), 40)])[0] == "falling"
    assert trend([(t0, 60), (t0 + timedelta(hours=2), 62)])[0] == "steady"
    assert trend([(t0, 60)])[0] == "unknown"


# --- API
def test_seeded_summary_trends(client):
    rs = client.get("/api/reports").json(); assert len(rs) == 18 and all(r["simulated"] for r in rs)
    tum = {s["street"]: s for s in client.get("/api/summary/Tumana").json()["streets"]}
    assert tum["Bayabas St"]["trend"] == "rising" and tum["Bayabas St"]["passability"] == "boats" and tum["Bayabas St"]["people_at_risk"]
    mal = {s["street"]: s for s in client.get("/api/summary/Malanday").json()["streets"]}
    assert mal["Rodriguez Ave"]["trend"] == "falling"
    nan = {s["street"]: s for s in client.get("/api/summary/Nangka").json()["streets"]}
    assert nan["Twin River Subd. Rd"]["trend"] == "steady"


def test_sitrep_bilingual_with_trend(client):
    sr = client.get("/api/sitrep/Tumana").json()
    assert "Bayabas St ↑" in sr["en"] and "rising" in sr["en"] and "tumataas" in sr["fil"]
    assert "naghihintay ng sagot" in sr["fil"]


def test_upload_ok_and_duplicate(client):
    p = find_photo(False)
    a = post(client, p, street="Dup St"); assert a.status_code == 201 and a.json()["status"] == "ok"
    b = post(client, p, street="Dup St"); assert b.json()["status"] == "duplicate" and b.json()["duplicate_of"] == a.json()["id"]
    assert [n for n, _ in a.json()["agent_trace"]] == ["get_nearby_reports", "merge_duplicates", "flag_people_at_risk", "ask_followup"]


def test_followup_flow_filipino(client):
    r = post(client, find_photo(True), note="Baha na dito sa amin").json()
    assert r["status"] == "needs_info" and r["depth_cm"] is None and r["lang"] == "fil" and "litrato" in r["question"]
    ans = client.post(f"/api/reports/{r['id']}/answer", json={"reference": "car_tire", "submerged_pct": 100})
    assert ans.status_code == 200 and ans.json()["status"] == "ok" and ans.json()["depth_cm"] == 65
    assert client.post(f"/api/reports/{r['id']}/answer", json={"reference": "door", "submerged_pct": 50}).status_code == 409


def test_followup_english_and_bad_answer(client):
    r = post(client, find_photo(True), note="water rising").json()
    assert r["lang"] == "en" and "door" in r["question"]
    assert client.post(f"/api/reports/{r['id']}/answer", json={"reference": "tree", "submerged_pct": 50}).status_code == 422
    assert any(x["id"] == r["id"] for x in client.get("/api/reports?status=needs_info").json())


def test_nearby_endpoint(client):
    rid = client.get("/api/reports").json()[0]["id"]
    assert len(client.get(f"/api/reports/{rid}/nearby?radius_m=100").json()) >= 2


def test_bad_coords(client):
    assert post(client, b"x", lat=200).status_code == 422


def test_meta_provider_fallback_without_key(tmp_path, monkeypatch):
    """Without a Meta key and with fallback on, meta provider uses mock — no 501."""
    # Empty (not deleted) so load_dotenv will not refill from project .env
    monkeypatch.setenv("META_API_KEY", "")
    monkeypatch.setenv("MODEL_API_KEY", "")
    monkeypatch.setenv("BAHABANTAY_META_FALLBACK", "true")
    c = TestClient(create_app(db_path=tmp_path / "m.db", provider="meta"))
    r = post(c, find_photo(False))
    assert r.status_code == 201
    assert r.json()["status"] in ("ok", "duplicate", "needs_info")


# --- eval
def test_eval_runs_on_simulated_set(tmp_path):
    from pathlib import Path
    items = json.loads((Path(eval_depth.ROOT) / "sample_data/eval/labeled_simulated.json").read_text())["items"]
    assert len(items) == 25 and all(i["simulated"] for i in items)
    res = eval_depth.evaluate(items)
    assert res["cant_tell"] == 4 and res["mae_cm"] < 15
    out = tmp_path / "r.md"; eval_depth.write_md(res, "x", out); assert "SIMULATED" in out.read_text()
