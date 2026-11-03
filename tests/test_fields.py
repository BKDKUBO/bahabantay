from datetime import datetime, timedelta, timezone
from app import assess, cells
from tests.test_app import client, find_photo, post  # noqa: F401

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def r(i, ago=5, **kw):
    return {"id": i, "reported_at": (NOW - timedelta(minutes=ago)).isoformat(), "lat": 14.65, "lng": 121.1, "barangay": "X",
            "street": "A St", "band": "cant_tell", "confidence": 0.0, "depth_cm": None, "water_level": None, "note": "",
            "kind": "flood", "people_at_risk": False, "assessment": {}, "simulated": False, **kw}


def test_level_from_reported_cm():
    assert assess.report_level(r(1, reported_depth_cm=45)) == ("knee", "user_reported")
    assert assess.report_level(r(1, reported_depth_cm=45, water_level="waist"))[0] == "waist"   # tap wins over typed cm
    a = assess.assess_incident([r(1, reported_depth_cm=95)], {}, [], NOW)
    assert a["level"] == "waist" and a["confidence"] == 0.65 and a["reported_depth_cm"] == 95


def test_car_not_passable_means_avoid():
    a = assess.assess_incident([r(1, water_level="knee", car_passable="no")], {}, [], NOW)
    assert a["action_label"] == "Avoid this area" and a["car_passable"] == "no" and a["tier"] != "monitor"
    assert "cars cannot pass" in a["priority_reason"]
    old = assess.assess_incident([r(1, ago=200, water_level="knee", car_passable="no")], {}, [], NOW)
    assert old["car_passable"] is None                                          # stale answer no longer drives the label


def test_trend_merges_with_rising():
    up = assess.assess_incident([r(1, 30, water_level="knee", rising="yes"), r(2, 5, water_level="knee", trend="receding")], {}, [], NOW)
    assert up["rising"] is False and up["trend"] == "receding" and "water receding" in up["priority_reason"]
    assert assess.assess_incident([r(1, water_level="knee", trend="rising")], {}, [], NOW)["rising"] is True


def test_cells_use_new_fields():
    c = cells.build([r(1, reported_depth_cm=70, car_passable="no", loc_source="gps", status="ok")], NOW)[0]
    assert c["depth_cm_weighted"] == 70 and c["cars_cannot_pass"] and c["level"] == "waist"


def test_api_fields_and_validation(client):
    ok = post(client, find_photo(True), trend="receding", car_passable="no", reported_depth_cm="50")
    assert ok.status_code == 201
    j = ok.json(); assert j["trend"] == "receding" and j["rising"] == "no" and j["car_passable"] == "no" and j["reported_depth_cm"] == 50
    legacy = post(client, find_photo(True), rising="yes").json()
    assert legacy["trend"] == "rising" and legacy["rising"] == "yes"
    assert post(client, find_photo(True), trend="sideways").status_code == 422
    assert post(client, find_photo(True), car_passable="maybe").status_code == 422
    assert post(client, find_photo(True), reported_depth_cm="900").status_code == 422
    d = post(client, find_photo(True), draft="true").json()
    assert d["understood"]["trend"] is None
    p = client.post(f"/api/reports/{d['id']}/publish", json={"trend": "rising", "car_passable": "yes", "reported_depth_cm": 20}).json()
    assert p["trend"] == "rising" and p["car_passable"] == "yes" and p["reported_depth_cm"] == 20
