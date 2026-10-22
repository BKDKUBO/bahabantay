import os, time, uuid
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from . import db, depth
from .aggregate import note_flags_risk, summarize
from .providers import get_providers

ROOT = Path(__file__).resolve().parent.parent
UPLOADS = Path(os.getenv("BAHABANTAY_UPLOADS", ROOT / "data" / "uploads"))
MAX_BYTES = 8 * 1024 * 1024


def create_app(db_path=None, provider=None) -> FastAPI:
    app = FastAPI(title="BahaBantay", version="0.1.0")
    conn = db.connect(db_path)
    vision, reporter = get_providers(provider)
    UPLOADS.mkdir(parents=True, exist_ok=True)

    def all_reports():
        return [db.row(r) for r in conn.execute("SELECT * FROM reports ORDER BY id")]

    @app.get("/api/health")
    def health():
        return {"ok": True, "provider": vision.name}

    @app.post("/api/reports", status_code=201)
    async def create_report(photo: UploadFile = File(...), lat: float = Form(...), lng: float = Form(...),
                            barangay: str = Form(...), street: str = Form(...), note: str = Form("")):
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise HTTPException(422, "invalid coordinates")
        data = await photo.read()
        if not data or len(data) > MAX_BYTES:
            raise HTTPException(413 if data else 422, "photo missing or too large")
        try:
            est = depth.run(data, vision)
        except NotImplementedError as e:
            raise HTTPException(501, str(e))
        name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.jpg"
        (UPLOADS / name).write_bytes(data)
        import json
        cur = conn.execute("""INSERT INTO reports(lat,lng,barangay,street,note,image_path,depth_cm,band,confidence,
            reference,masks,people_at_risk,simulated,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?)""",
            (lat, lng, barangay.strip(), street.strip(), note, f"/uploads/{name}", est["depth_cm"], est["band"],
             est["confidence"], est["reference"], json.dumps(est["masks"]), int(note_flags_risk(note)), vision.name))
        conn.commit()
        return db.row(conn.execute("SELECT * FROM reports WHERE id=?", (cur.lastrowid,)).fetchone())

    @app.get("/api/reports")
    def list_reports(barangay: str | None = None):
        rs = all_reports()
        return [r for r in rs if not barangay or r["barangay"] == barangay]

    @app.get("/api/barangays")
    def barangays():
        return sorted({r["barangay"] for r in all_reports()})

    @app.get("/api/summary/{barangay}")
    def summary(barangay: str):
        return summarize(all_reports(), barangay)

    @app.get("/api/sitrep/{barangay}")
    def sitrep(barangay: str):
        s = summarize(all_reports(), barangay)
        if not s["streets"]:
            raise HTTPException(404, "no reports for barangay")
        try:
            return {"barangay": barangay, "provider": reporter.name,
                    "en": reporter.situation_report(s, "en"), "fil": reporter.situation_report(s, "fil"), "summary": s}
        except NotImplementedError as e:
            raise HTTPException(501, str(e))

    app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")
    app.mount("/samples", StaticFiles(directory=ROOT / "sample_data" / "images"), name="samples")

    @app.get("/")
    def index():
        return FileResponse(ROOT / "static" / "index.html")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
    app.state.conn = conn
    return app


app = create_app()
