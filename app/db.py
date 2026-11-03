import json, os, sqlite3, threading
from pathlib import Path

DB_PATH = Path(os.getenv("BAHABANTAY_DB", Path(__file__).resolve().parent.parent / "data" / "bahabantay.db"))

SCHEMA = """CREATE TABLE IF NOT EXISTS reports(
 id INTEGER PRIMARY KEY AUTOINCREMENT, reported_at TEXT NOT NULL,
 lat REAL NOT NULL, lng REAL NOT NULL, barangay TEXT NOT NULL, street TEXT NOT NULL,
 note TEXT, lang TEXT DEFAULT 'en', image_path TEXT, depth_cm INTEGER, band TEXT, confidence REAL,
 reference TEXT, reason TEXT, masks TEXT, people_at_risk INTEGER DEFAULT 0, simulated INTEGER DEFAULT 0,
 status TEXT DEFAULT 'ok', question TEXT, duplicate_of INTEGER, provider TEXT,
 water_level TEXT, rising TEXT, kind TEXT DEFAULT 'flood', loc_source TEXT, assessment TEXT)"""
EXTRA = {"water_level": "TEXT", "rising": "TEXT", "kind": "TEXT DEFAULT 'flood'", "loc_source": "TEXT", "assessment": "TEXT", "psgc_code": "TEXT", "client_id": "TEXT"}
SIDE = ["CREATE TABLE IF NOT EXISTS votes(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, vote TEXT NOT NULL, at TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)",
        "CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id INTEGER NOT NULL, action TEXT NOT NULL, note TEXT, at TEXT NOT NULL)"]
COLS = ["reported_at", "lat", "lng", "barangay", "street", "note", "lang", "image_path", "depth_cm", "band", "confidence",
        "reference", "reason", "masks", "people_at_risk", "simulated", "status", "question", "duplicate_of", "provider",
        "water_level", "rising", "kind", "loc_source", "assessment", "psgc_code", "client_id"]


class _Rows(list):
    lastrowid = None
    def fetchone(self): return self[0] if self else None
    def fetchall(self): return list(self)


class Locked:
    """One SQLite connection shared by FastAPI's threadpool. Every statement runs and is fully
    fetched under a lock, so concurrent requests can't interleave cursors."""
    def __init__(self, c): self._c, self._lock = c, threading.RLock()
    def execute(self, sql, args=()):
        with self._lock:
            cur = self._c.execute(sql, args); out = _Rows(cur.fetchall()); out.lastrowid = cur.lastrowid; return out
    def commit(self):
        with self._lock: self._c.commit()


def connect(path=None):
    p = Path(path or DB_PATH); p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, check_same_thread=False); c.row_factory = sqlite3.Row
    have = [r[1] for r in c.execute("PRAGMA table_info(reports)")]
    if have and "reported_at" not in have:   # old v0.1 schema: local demo data only, rebuild
        c.execute("DROP TABLE reports")
    c.execute(SCHEMA)
    have = [r[1] for r in c.execute("PRAGMA table_info(reports)")]
    for col, typ in EXTRA.items():
        if col not in have: c.execute(f"ALTER TABLE reports ADD COLUMN {col} {typ}")
    for q in SIDE: c.execute(q)
    c.commit(); return Locked(c)


def insert(c, rec: dict) -> int:
    rec = {**rec, "masks": json.dumps(rec.get("masks", [])), "people_at_risk": int(bool(rec.get("people_at_risk"))),
           "simulated": int(bool(rec.get("simulated"))),
           "assessment": json.dumps(rec.get("assessment") or {}), "kind": rec.get("kind") or "flood"}
    cur = c.execute(f"INSERT INTO reports({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})", [rec.get(k) for k in COLS])
    c.commit(); return cur.lastrowid


def row(r):
    d = dict(r); d["masks"] = json.loads(d["masks"] or "[]")
    d["people_at_risk"] = bool(d["people_at_risk"]); d["simulated"] = bool(d["simulated"])
    d["assessment"] = json.loads(d.get("assessment") or "{}"); d["kind"] = d.get("kind") or "flood"; return d
