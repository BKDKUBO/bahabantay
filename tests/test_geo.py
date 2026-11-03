from app import geo
from tests.test_app import client, find_photo, post  # noqa: F401


def test_dataset_is_nationwide():
    rows = geo.all_rows()
    assert len(rows) > 42000
    assert sum(r["lat"] is not None for r in rows) / len(rows) > 0.99
    assert len({r["label"] for r in rows}) == len(rows)          # labels unique


def test_search_mindanao_and_marikina(client):
    hits = client.get("/api/barangays/search", params={"q": "poblacion davao"}).json()
    assert hits and len(hits) <= 8 and all("Davao" in h["label"] for h in hits)
    assert all(not h["covered"] for h in hits)
    cot = client.get("/api/barangays/search", params={"q": "rosary heights cotabato"}).json()
    assert cot and cot[0]["name"].startswith("Rosary Heights")
    t = client.get("/api/barangays/search", params={"q": "tumana"}).json()
    assert t[0]["label"] == "Tumana" and t[0]["covered"]          # Marikina demo first, bare label
    assert client.get("/api/barangays/search", params={"q": "a"}).json() == []
    assert len(client.get("/api/barangays/search", params={"q": "san", "limit": 500}).json()) <= 20


def test_accents_and_nearest(client):
    assert any(h["name"] == "Tañong" for h in client.get("/api/barangays/search", params={"q": "tanong marikina"}).json())
    n = client.get("/api/barangays/nearest", params={"lat": 14.6588, "lng": 121.0961}).json()
    assert n[0]["label"] == "Tumana" and n[0]["distance_km"] < 0.5
    assert client.get("/api/barangays/nearest", params={"lat": 7.07, "lng": 125.61}).json()[0]["city"] == "Davao City"
    assert client.get("/api/barangays/nearest", params={"lat": 99, "lng": 0}).status_code == 422


def test_outside_coverage_report_and_help(client):
    label = client.get("/api/barangays/search", params={"q": "rosary heights cotabato"}).json()[0]["label"]
    r = post(client, find_photo(False), barangay=label, lat=7.22, lng=124.25)
    assert r.status_code == 201 and r.json()["barangay"] == label and r.json()["psgc_code"]
    inc = client.get("/api/incidents", params={"barangay": label}).json()
    assert inc and inc[0]["covered"] is False
    # help with no GPS in a barangay with no reports: falls back to the PSGC centroid, marked approximate
    h = client.post("/api/help", json={"barangay": "Poblacion, Banaybanay, Davao Oriental", "street": "Rizal St"})
    assert h.status_code == 201 and h.json()["incident"]["approximate"] and h.json()["incident"]["covered"] is False
    assert client.get("/api/incidents", params={"barangay": "Malanday"}).json()[0]["covered"] is True


def test_find_counts_and_disambiguates(client):
    r = client.get("/api/barangays/find", params={"q": "san isidro"}).json()
    assert r["total"] > 100 and len(r["items"]) == 20
    assert r["items"][0]["city"] == "Quezon City"                       # Marikina/QC first
    assert all(h["name"] == "San Isidro" for h in r["items"][:5])        # exact name before "San Isidro Norte"
    provs = {h["province"] for h in r["items"]}
    assert len(provs) >= 5 and all(h["region"] and h["city"] for h in r["items"])
    assert len({h["label"] for h in r["items"]}) == len(r["items"])     # same name, distinct labels


def test_qualifying_tokens_narrow(client):
    cebu = client.get("/api/barangays/find", params={"q": "san isidro, cebu"}).json()
    assert 0 < cebu["total"] < 20 and all("Cebu" in h["city"] + h["province"] for h in cebu["items"][:6])
    dav = client.get("/api/barangays/find", params={"q": "poblacion davao"}).json()
    assert dav["items"] and all("Davao" in (h["city"] + h["province"]) for h in dav["items"])
    assert all(h["name"].lower().startswith("poblacion") for h in dav["items"][:3])
    # a place word alone never lists a whole province: the name must match
    assert client.get("/api/barangays/find", params={"q": "cebu"}).json()["total"] < 50


def test_find_empty_and_short(client):
    assert client.get("/api/barangays/find", params={"q": "zzqxw"}).json() == {"q": "zzqxw", "total": 0, "items": []}
    assert client.get("/api/barangays/find", params={"q": "a"}).json()["items"] == []
    assert geo.short_region("Region XI (Davao Region)") == "Davao Region"
