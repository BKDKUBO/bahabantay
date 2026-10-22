"""Load ~10 SIMULATED sample reports (Marikina, flood-prone area). Not real data."""
import json, sys
from pathlib import Path
from PIL import Image, ImageDraw
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import db
from app.aggregate import note_flags_risk
from app.depth import band_for

IMG = ROOT / "sample_data" / "images"
SAMPLES = [  # barangay, street, lat, lng, depth_cm, reference, note
 ("Tumana", "Bayabas St", 14.6578, 121.0992, 120, "door", "Stranded family on 2nd floor, need tulong"),
 ("Tumana", "Bayabas St", 14.6582, 121.0998, 95, "person", "Waist-deep near the chapel"),
 ("Tumana", "Kamagong St", 14.6560, 121.1010, 70, "jeepney", "Jeepneys stuck"),
 ("Tumana", "Molave St", 14.6549, 121.0975, 30, "car_tire", "Half the tire under water"),
 ("Tumana", "Ilang-Ilang St", 14.6593, 121.1025, 8, "curb", "Curb barely covered"),
 ("Malanday", "M. H. del Pilar St", 14.6512, 121.0960, 140, "door", "Matanda naiipit sa bahay"),
 ("Malanday", "Rodriguez Ave", 14.6495, 121.0941, 45, "person", "Knee to thigh deep"),
 ("Malanday", "Sampaguita St", 14.6503, 121.0928, 15, "car_tire", ""),
 ("Nangka", "Twin River Subd. Rd", 14.6705, 121.1088, 60, "person", "Rising fast"),
 ("Nangka", "Bagong Silang St", 14.6690, 121.1102, 0, "curb", "Dry for now"),
]
REF_H = {"person": 160, "door": 210, "car_tire": 65, "jeepney": 200, "curb": 15}


def placeholder(i, ref, depth_cm, path):
    im = Image.new("RGB", (480, 360), (205, 210, 215)); d = ImageDraw.Draw(im)
    top, bottom = 108, 324
    d.rectangle((192, top, 288, bottom), fill=(120, 90, 60)); d.text((196, top + 4), ref, fill="white")
    frac = min(1, depth_cm / REF_H[ref]); wl = int(bottom - frac * (bottom - top))
    if depth_cm: d.rectangle((0, wl, 480, 360), fill=(70, 110, 160))
    d.text((10, 10), f"SIMULATED sample #{i+1} - placeholder image", fill="black")
    d.text((10, 26), f"~{depth_cm} cm", fill="black"); im.save(path, "JPEG")


def main(db_path=None):
    IMG.mkdir(parents=True, exist_ok=True)
    c = db.connect(db_path)
    c.execute("DELETE FROM reports WHERE simulated=1")
    for i, (b, s, lat, lng, cm, ref, note) in enumerate(SAMPLES):
        name = f"sample_{i+1:02d}.jpg"; placeholder(i, ref, cm, IMG / name)
        masks = [{"label": ref, "bbox": [0.4, 0.3, 0.6, 0.9], "score": 0.9}]
        c.execute("""INSERT INTO reports(lat,lng,barangay,street,note,image_path,depth_cm,band,confidence,reference,
          masks,people_at_risk,simulated,provider) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,'simulated')""",
          (lat, lng, b, s, f"[SIMULATED] {note}".strip(), f"/samples/{name}", cm, band_for(cm), 0.9, ref,
           json.dumps(masks), int(note_flags_risk(note))))
    c.commit(); print(f"seeded {len(SAMPLES)} SIMULATED reports")


if __name__ == "__main__":
    main()
