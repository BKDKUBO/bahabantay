import json, os, sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("BAHABANTAY_DB", Path(__file__).resolve().parent.parent / "data" / "bahabantay.db"))

SCHEMA = """CREATE TABLE IF NOT EXISTS reports(
 id INTEGER PRIMARY KEY AUTOINCREMENT, reported_at TEXT NOT NULL,
 lat REAL NOT NULL, lng REAL NOT NULL, barangay TEXT NOT NULL, street TEXT NOT NULL,
 note TEXT, lang TEXT DEFAULT 'en', image_path TEXT, depth_cm INTEGER, band TEXT, confidence REAL,
 reference TEXT, reason TEXT, masks TEXT, people_at_risk INTEGER DEFAULT 0, simulated INTEGER DEFAULT 0,
 status TEXT DEFAULT 'ok', question TEXT, duplicate_of INTEGER, provider TEXT)"""
COLS = ["reported_at", "lat", "lng", "barangay", "street", "note", "lang", "image_path", "depth_cm", "band", "confidence",
        "reference", "reason", "masks", "people_at_risk", "simulated", "status", "question", "duplicate_of", "provider"]


def connect(path=None):
    p = Path(path or DB_PATH); p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, check_same_thread=False); c.row_factory = sqlite3.Row
    have = [r[1] for r in c.execute("PRAGMA table_info(reports)")]
    if have and "reported_at" not in have:   # old v0.1 schema: local demo data only, rebuild
        c.execute("DROP TABLE reports")
    c.execute(SCHEMA); return c


def insert(c, rec: dict) -> int:
    rec = {**rec, "masks": json.dumps(rec.get("masks", [])), "people_at_risk": int(bool(rec.get("people_at_risk"))),
           "simulated": int(bool(rec.get("simulated")))}
    cur = c.execute(f"INSERT INTO reports({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})", [rec.get(k) for k in COLS])
    c.commit(); return cur.lastrowid


def row(r):
    d = dict(r); d["masks"] = json.loads(d["masks"] or "[]")
    d["people_at_risk"] = bool(d["people_at_risk"]); d["simulated"] = bool(d["simulated"]); return d
