import json, os, sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("BAHABANTAY_DB", Path(__file__).resolve().parent.parent / "data" / "bahabantay.db"))

SCHEMA = """CREATE TABLE IF NOT EXISTS reports(
 id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT (datetime('now')),
 lat REAL NOT NULL, lng REAL NOT NULL, barangay TEXT NOT NULL, street TEXT NOT NULL,
 note TEXT, image_path TEXT, depth_cm INTEGER, band TEXT, confidence REAL,
 reference TEXT, masks TEXT, people_at_risk INTEGER DEFAULT 0, simulated INTEGER DEFAULT 0,
 provider TEXT)"""


def connect(path=None):
    p = Path(path or DB_PATH); p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, check_same_thread=False); c.row_factory = sqlite3.Row
    c.execute(SCHEMA); return c


def row(r):
    d = dict(r); d["masks"] = json.loads(d["masks"] or "[]")
    d["people_at_risk"] = bool(d["people_at_risk"]); d["simulated"] = bool(d["simulated"]); return d
