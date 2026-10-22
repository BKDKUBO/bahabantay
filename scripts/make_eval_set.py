"""Generate the SIMULATED labeled eval set (25 items). Deterministic (seed 42).

Each item = synthetic segmentation masks + a known "true" depth. This only
tests the depth math and the can't-tell logic, NOT real-world accuracy.
Replace with real flood photos that have tape-measured depths.
"""
import json, random, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.depth import REF_HEIGHT_CM

OUT = ROOT / "sample_data" / "eval" / "labeled_simulated.json"


def main():
    rnd = random.Random(42); items = []
    refs = list(REF_HEIGHT_CM)
    for i in range(25):
        ref = refs[i % len(refs)]; H = REF_HEIGHT_CM[ref]
        true = round(rnd.uniform(0, min(H, 150)))
        top, bottom = 0.30, 0.90
        noise = rnd.gauss(0, 0.05)                        # segmentation error on waterline
        wl = bottom - (true / H) * (bottom - top) + noise * (bottom - top)
        masks = []
        kind = "normal"
        if i in (6, 19):
            kind = "no_reference"
        else:
            score = 0.40 if i in (11, 23) else round(rnd.uniform(0.7, 0.98), 2)
            if score < 0.5: kind = "low_confidence"
            masks.append({"label": ref, "bbox": [0.4, top, 0.6, bottom], "score": score})
        if true > 0:
            masks.append({"label": "water", "bbox": [0.0, max(0.0, min(1.0, wl)), 1.0, 1.0], "score": round(rnd.uniform(0.8, 0.98), 2)})
        items.append({"id": f"SIM-{i+1:02d}", "simulated": True, "kind": kind, "reference": ref, "true_depth_cm": true, "masks": masks})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"note": "SIMULATED labeled set. Not real photos. Replace with real flood photos + measured depths.",
                               "items": items}, indent=1))
    print(f"wrote {len(items)} SIMULATED items to {OUT}")


if __name__ == "__main__":
    main()
