"""Load sample reports incl. time series (Marikina, flood-prone area). Synthetic, NOT real floods.

Sample reports are labeled "Sample report" in the UI and are not analyzed by the live models;
new photos submitted in the app are.

Timestamps are relative to "now" so the 6-hour trend window always has data.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db
from app.agent import QUESTIONS, detect_lang
from app.aggregate import note_flags_risk
from app.assess import extract_text
from app.depth import REF_HEIGHT_CM, band_for

IMG = ROOT / "sample_data" / "images"
# barangay, street, lat, lng, minutes_ago, depth_cm (None = can't tell), reference, note
SAMPLES = [
 # Bayabas St: RISING time series
 ("Tumana", "Bayabas St", 14.6576, 121.0990, 170, 60, "door", "Hanggang tuhod pa lang"),
 ("Tumana", "Bayabas St", 14.6578, 121.0993, 110, 85, "person", "Waist-deep near the chapel"),
 ("Tumana", "Bayabas St", 14.6580, 121.0995, 55, 105, "door", "Tumataas ang tubig"),
 ("Tumana", "Bayabas St", 14.6582, 121.0998, 10, 125, "door", "Stranded family on 2nd floor, need tulong"),
 ("Tumana", "Kamagong St", 14.6560, 121.1010, 40, 70, "jeepney", "Jeepneys stuck, may kable ng kuryente sa tubig"),
 ("Tumana", "Molave St", 14.6549, 121.0975, 35, 30, "car_tire", "Half the tire under water"),
 ("Tumana", "Ilang-Ilang St", 14.6593, 121.1025, 25, 8, "curb", "Curb barely covered"),
 ("Tumana", "Narra St", 14.6566, 121.0960, 15, None, None, "Baha na dito! Ang lalim"),         # needs info (FIL)
 # Malanday: Rodriguez Ave FALLING time series
 ("Malanday", "M. H. del Pilar St", 14.6512, 121.0960, 20, 140, "door", "Matanda naiipit sa bahay"),
 ("Malanday", "Rodriguez Ave", 14.6493, 121.0939, 200, 80, "person", "Deep, cars stalled"),
 ("Malanday", "Rodriguez Ave", 14.6495, 121.0941, 120, 62, "person", "Going down a bit"),
 ("Malanday", "Rodriguez Ave", 14.6497, 121.0943, 30, 40, "car_tire", "Knee deep now"),
 ("Malanday", "Sampaguita St", 14.6503, 121.0928, 50, 15, "car_tire", ""),
 ("Malanday", "Gumamela St", 14.6520, 121.0920, 12, None, None, "Water everywhere, photo from window"),  # needs info (EN)
 # Nangka: Twin River STEADY time series
 ("Nangka", "Twin River Subd. Rd", 14.6703, 121.1086, 180, 58, "person", "Mataas pa rin"),
 ("Nangka", "Twin River Subd. Rd", 14.6705, 121.1088, 90, 60, "person", "Same level"),
 ("Nangka", "Twin River Subd. Rd", 14.6707, 121.1090, 20, 61, "person", "Hindi gumagalaw ang tubig"),
 ("Nangka", "Bagong Silang St", 14.6690, 121.1102, 30, 0, "curb", "Dry for now"),
]


def placeholder(i, ref, depth_cm, path):
    im = Image.new("RGB", (480, 360), (205, 210, 215)); d = ImageDraw.Draw(im)
    top, bottom = 108, 324
    if ref:
        d.rectangle((192, top, 288, bottom), fill=(120, 90, 60)); d.text((196, top + 4), ref, fill="white")
        frac = min(1, (depth_cm or 0) / REF_HEIGHT_CM[ref]); wl = int(bottom - frac * (bottom - top))
    else:
        wl = 150
    if depth_cm != 0: d.rectangle((0, wl, 480, 360), fill=(70, 110, 160))
    d.text((10, 10), f"Sample report #{i+1} - placeholder image (synthetic)", fill="black")
    d.text((10, 26), f"~{depth_cm} cm" if depth_cm is not None else "no reference object", fill="black"); im.save(path, "JPEG")


def main(db_path=None, now=None):
    IMG.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    c = db.connect(db_path)
    c.execute("DELETE FROM reports WHERE simulated=1"); c.execute("DELETE FROM votes"); c.execute("DELETE FROM reviews"); c.commit()
    for i, (b, s, lat, lng, ago, cm, ref, note) in enumerate(SAMPLES):
        name = f"sample_{i+1:02d}.jpg"; placeholder(i, ref, cm, IMG / name)
        lang = detect_lang(note)
        rec = {"reported_at": (now - timedelta(minutes=ago)).isoformat(timespec="seconds"), "lat": lat, "lng": lng,
               "barangay": b, "street": s, "note": note, "lang": lang,
               "image_path": f"/samples/{name}", "depth_cm": cm, "band": band_for(cm), "confidence": 0.9 if ref else 0.0,
               "reference": ref, "reason": None if ref else "no_reference",
               "masks": [{"label": ref, "bbox": [0.4, 0.3, 0.6, 0.9], "score": 0.9}] if ref else [],
               "people_at_risk": note_flags_risk(note) or extract_text(note)["people_at_risk"], "simulated": True, "provider": "sample", "kind": "flood", "loc_source": "map",
               "assessment": {**extract_text(note), "source": "sample"},
               "status": "ok" if ref else "needs_info", "question": None if ref else QUESTIONS["no_reference"][lang]}
        db.insert(c, rec)
    print(f"seeded {len(SAMPLES)} sample reports (synthetic)")


if __name__ == "__main__":
    main()
