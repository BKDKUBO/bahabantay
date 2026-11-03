import io
from datetime import datetime, timedelta, timezone
from app import assess
from tests.test_app import client, find_photo, post  # noqa: F401  (fixture reuse)

T0 = datetime(2026, 11, 2, tzinfo=timezone.utc)


def rep(i, mins=0, street="A St", band="cant_tell", conf=0.0, level=None, note="", kind="flood", dup=None, sim=False):
    return {"id": i, "reported_at": (T0 + timedelta(minutes=mins)).isoformat(), "lat": 14.65, "lng": 121.1, "barangay": "X",
            "street": street, "band": band, "confidence": conf, "depth_cm": None, "water_level": level, "note": note,
            "kind": kind, "duplicate_of": dup, "people_at_risk": False, "assessment": assess.extract_text(note), "simulated": sim}


def A(rs, votes=None, reviews=None):
    return assess.assess_incident(rs, votes or {}, reviews or [], T0 + timedelta(minutes=30))


def test_extract_taglish():
    e = assess.extract_text("Hanggang baywang na, may matanda sa 2nd floor hindi makalabas, may kuryente sa poste")
    assert e["water_level"] == "waist" and e["people_at_risk"]
    assert {"stranded_person", "vulnerable_person", "live_wire"} <= set(e["hazards"])
    assert assess.extract_text("Hindi na tumataas, bumababa na")["rising"] == "no"


def test_clean_extraction_drops_unknown():
    c = assess.clean_extraction({"hazards": ["live_wire", "aliens"], "water_level": "ocean", "confidence": 7})
    assert c["hazards"] == ["live_wire"] and c["water_level"] is None and c["confidence"] == 1.0


def test_rule_never_safe_from_single_photo():
    a = A([rep(1, band="none", conf=0.9)])
    assert a["action_label"] == "Needs confirmation" and a["ladder"] == "user_reported"
    b = A([rep(1, band="none", conf=0.9), rep(2, 5, band="none", conf=0.9, dup=1)])
    assert b["action_label"] == "Safe to pass" and b["ladder"] == "ai_grouped" and b["needs_human_verification"]


def test_unknown_depth_needs_confirmation_and_no_escalation_without_conf():
    a = A([rep(1)])
    assert a["confidence"] is None and a["action_label"] == "Needs confirmation" and a["tier"] == "needs_verification"


def test_people_at_risk_critical_and_help():
    a = A([rep(1, band="knee", conf=0.8, note="May bata, tulong!")])
    assert a["severity"] == "critical" and a["action_label"] == "Help may be needed" and a["tier"] == "critical"
    h = A([rep(1, kind="help", note="kailangan ng tulong")])
    assert h["tier"] == "critical" and h["people_at_risk"]


def test_ladder_and_confidence_update():
    rs = [rep(1, band="knee", conf=0.7)]
    c1 = A(rs)["confidence"]
    rs.append(rep(2, 5, band="knee", conf=0.7, dup=1)); c2 = A(rs)["confidence"]
    c3 = A(rs, {"still": 2})["confidence"]
    assert c1 < c2 < c3 and A(rs, {"still": 2})["ladder"] == "community_corroborated"
    v = A(rs, {"still": 2}, [{"action": "confirm", "at": "z"}])
    assert v["ladder"] == "responder_verified" and not v["needs_human_verification"]


def test_area_danger_needs_corroboration_or_people():
    deep = dict(A([rep(1, band="waist", conf=0.9)]), id=1, reports=1)
    assert assess.area_status([deep])["status"] == "watch"
    corr = dict(A([rep(1, band="waist", conf=0.9)], {"still": 2}), id=1, reports=1)
    assert assess.area_status([corr])["status"] == "danger"


def test_cluster_by_street_and_window():
    a, b, far = rep(1), rep(2, 30, street="a street"), rep(3, 200)
    b["lat"] = 14.66  # >60 m away but same normalized street
    assert assess.cluster_root(b, [a]) == 1 and assess.cluster_root(far, [a]) is None


def test_advisory_template_sms_len():
    inc = [{"street": "Bayabas St", "level": "waist", "action_label": "Avoid this area", "severity": "high", "rising": True,
            "people_at_risk": True, "reports": 4, "ladder": "ai_grouped", "updated_min_ago": 3}]
    t = assess.advisory_template({"barangay": "Tumana", "area": {"text": "Watch"}, "incidents": inc})
    assert "Bayabas St" in t["en"] and "Iwasan" in t["fil"] and len(t["sms"]) <= 160


# --- API
def test_health_mock(client):
    h = client.get("/api/health").json(); assert h["provider"] == "mock" and h["models"] is None


def test_incidents_public_vs_responder(client):
    pub = client.get("/api/incidents").json(); res = client.get("/api/incidents?view=responder").json()
    assert pub and all("evidence" not in i for i in pub) and all("evidence" in i for i in res)
    assert all(round(i["lat"], 3) == i["lat"] for i in pub) and all(i["sample"] for i in pub)
    bay = next(i for i in res if i["street"] == "Bayabas St")
    assert bay["tier"] == "critical" and bay["reports"] >= 2


def test_draft_publish_flow(client):
    r = post(client, find_photo(False), street="Draft St", water_level="knee", rising="yes", note="tumataas", draft="true").json()
    assert r["status"] == "draft" and r["understood"]["reporter_level"] == "knee"
    assert all(i["street"] != "Draft St" for i in client.get("/api/incidents").json())
    p = client.post(f"/api/reports/{r['id']}/publish", json={"water_level": "waist"}).json()
    assert p["status"] in ("ok", "needs_info") and p["water_level"] == "waist" and p["incident"]["street"] == "Draft St"
    assert client.post(f"/api/reports/{r['id']}/publish", json={}).status_code == 409


def test_vote_review_and_escalate_rule(client):
    inc = next(i for i in client.get("/api/incidents").json() if i["street"] == "Kamagong St")
    v = client.post(f"/api/incidents/{inc['id']}/vote", json={"vote": "still"}).json()
    v = client.post(f"/api/incidents/{inc['id']}/vote", json={"vote": "still"}).json()
    assert v["votes"]["still"] == 2 and v["ladder"] == "community_corroborated"
    assert client.post(f"/api/incidents/{inc['id']}/vote", json={"vote": "maybe"}).status_code == 422
    c = client.post(f"/api/incidents/{inc['id']}/review", json={"action": "confirm"}).json()
    assert c["ladder"] == "responder_verified" and any(e["source"] == "responder" for e in c["evidence"])
    narra = next(i for i in client.get("/api/incidents").json() if i["street"] == "Narra St")
    assert narra["confidence"] is None
    assert client.post(f"/api/incidents/{narra['id']}/review", json={"action": "escalate"}).status_code == 409
    assert client.post("/api/incidents/99999/vote", json={"vote": "still"}).status_code == 404


def test_help_request_goes_to_top(client):
    r = client.post("/api/help", json={"barangay": "Nangka", "street": "Bagong Silang St", "note": "Lola namin di makalakad"})
    assert r.status_code == 201 and r.json()["incident"]["tier"] == "critical" and r.json()["incident"]["approximate"]
    q = client.get("/api/incidents?view=responder&barangay=Nangka").json()
    assert q[0]["kind"] == "help"
    pub = next(i for i in client.get("/api/incidents?barangay=Nangka").json() if i["kind"] == "help")
    assert pub["photo"] is None
    assert client.post("/api/help", json={"barangay": "Nowhere", "street": "x"}).status_code == 422


def test_area_and_advisory(client):
    a = client.get("/api/area/Tumana").json()
    assert a["status"] in ("watch", "danger") and a["incidents"] > 0 and a["updated_min_ago"] is not None
    adv = client.get("/api/advisory/Tumana").json()
    assert adv["provider"] == "mock" and "Tumana" in adv["en"] and adv["fil"] and len(adv["sms"]) <= 160


def test_meta_extract_and_advisory_fallback(monkeypatch):
    from app.providers import meta
    monkeypatch.setenv("BAHABANTAY_META_FALLBACK", "true")
    def boom(*a, **k): raise RuntimeError("down")
    monkeypatch.setattr(meta, "get_client", boom)
    r = meta.MetaReports()
    before = meta.FALLBACKS["count"]
    e = r.extract("May kuryente sa tubig", {})
    assert e["source"] == "mock-fallback" and "live_wire" in e["hazards"]
    assert r.advisory({"barangay": "T", "area": {"text": "x"}, "incidents": []})["provider"] == "mock-fallback"
    assert meta.FALLBACKS["count"] == before + 2
    seg = meta.MetaVision().segment(b"x", ["water", "person"]); assert seg.source == "mock-fallback"


def test_meta_extract_parses_model_json(monkeypatch):
    from app.providers import meta
    monkeypatch.setattr(meta, "get_client", lambda: object())
    monkeypatch.setattr(meta, "_muse_chat", lambda c, m, **k: '```json\n{"hazards":["strong_current","x"],"people_at_risk":true,"water_level":"waist","rising":"yes","confidence":0.8}\n```')
    e = meta.MetaReports().extract("rumaragasa ang tubig", {})
    assert e == {"hazards": ["strong_current"], "people_at_risk": True, "water_level": "waist", "rising": "yes",
                 "summary_en": None, "confidence": 0.8, "source": "meta"}


def test_index_has_no_hardcoded_mock_banner(client):
    html = client.get("/").text
    assert "mock vision/report provider" not in html and "SIMULATED" not in html and "/api/health" in html


def test_live_wire_means_avoid_even_without_photo_depth():
    a = A([rep(1, note="may kable ng kuryente sa tubig")])
    assert a["action_label"] == "Avoid this area"


def test_report_eval_runs_on_mock(tmp_path):
    from scripts import eval_reports
    res = eval_reports.main([])
    assert res["n"] >= 25 and 0 <= res["severity_agreement"] <= 1 and 0 <= res["group_pair_acc"] <= 1


# ---------- Nov 3 fixes
def test_avoid_this_area_never_in_monitor():
    a = A([rep(1, band="knee", conf=0.9), rep(2, 5, band="knee", conf=0.9, dup=1)])
    assert a["action_label"] == "Avoid this area" and a["tier"] != "monitor"
    v = A([rep(1, band="knee", conf=0.9)], reviews=[{"action": "confirm", "at": "x"}])
    assert v["action_label"] == "Avoid this area" and v["tier"] == "critical"


def test_freshness_fields():
    a = A([rep(1, band="knee", conf=0.9), rep(2, 20, band="knee", conf=0.9, dup=1)])
    assert a["reported_min_ago"] == 30 and a["updated_min_ago"] == 10


def test_no_longer_flooded_clears_after_two_votes():
    rs = [rep(1, band="waist", conf=0.9)]
    one = A(rs, {"gone": 1})
    assert one["flood_status"] == "clear_reported" and one["action_label"] == "Avoid this area"
    two = A(rs, {"gone": 2})
    assert two["flood_status"] == "cleared" and two["action_label"] == "Safe to pass" and two["tier"] == "monitor"
    assert two["ladder"] == "community_corroborated"
    outvoted = A(rs, {"gone": 2, "still": 3})
    assert outvoted["flood_status"] != "cleared"


def test_help_request_not_cleared_by_votes():
    a = A([rep(1, kind="help", note="tulong")], {"gone": 5})
    assert a["flood_status"] == "active" and a["tier"] == "critical"


def test_gone_vote_endpoint(client):
    inc = client.get("/api/incidents?barangay=Malanday").json()
    iid = next(i["id"] for i in inc if i["kind"] == "flood")
    client.post(f"/api/incidents/{iid}/vote", json={"vote": "gone"})
    r = client.post(f"/api/incidents/{iid}/vote", json={"vote": "gone"}).json()
    assert r["no_longer_flooded_votes"] == 2 and r["flood_status"] in ("cleared", "clear_reported")


def test_page_has_hotlines_and_loading_state(client):
    h = client.get("/").text
    for n in ("tel:161", "tel:122", "No longer flooded", "advBtn", "Reported "):
        assert n in h


def test_same_street_name_in_different_cities_never_merges():
    from app import geo
    a = {**rep(1, street="M. H. del Pilar St"), "barangay": "Malanday", "psgc_code": "1380702000"}
    b = {**rep(2, 3, street="M. H. Del Pilar Street"), "barangay": "Poblacion, Makati City, Metro Manila", "psgc_code": "1380300000"}
    g = assess.group([a, b])
    assert len(g) == 2 and assess.cluster_root(b, [a]) is None
    # same barangay + street still merges
    c = {**rep(3, 5, street="M. H. del Pilar St"), "barangay": "Malanday", "psgc_code": "1380702000"}
    assert len(assess.group([a, b, c])) == 2
    assert geo.place_label("Malanday") == "Malanday, Marikina City"
