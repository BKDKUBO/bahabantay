"""Depth estimation from segmentation masks using typical reference heights."""
from __future__ import annotations
from .providers.base import Segmentation, VisionProvider

REF_HEIGHT_CM = {"person": 160, "door": 210, "car_tire": 65, "jeepney": 200, "curb": 15}
PROMPTS = ["water", *REF_HEIGHT_CM.keys()]


def band_for(cm: float) -> str:
    if cm < 3: return "none"
    if cm < 20: return "ankle"
    if cm < 55: return "knee"
    if cm < 110: return "waist"
    return "chest"


def passability(cm: float) -> str:
    if cm < 25: return "all"
    if cm < 60: return "trucks"
    return "boats"


def estimate(seg: Segmentation) -> dict:
    water = max(seg.of("water"), key=lambda m: m.score, default=None)
    refs = [m for m in seg.masks if m.label in REF_HEIGHT_CM]
    if not refs:
        return {"depth_cm": None, "band": "unknown", "confidence": 0.0, "reference": None}
    ref = max(refs, key=lambda m: m.score)
    x0, top, x1, bottom = ref.bbox
    if water is None:
        depth = 0.0
    else:
        waterline = max(top, min(bottom, water.bbox[1]))
        depth = (bottom - waterline) / (bottom - top) * REF_HEIGHT_CM[ref.label]
    conf = round(ref.score * (water.score if water else 0.9), 2)
    return {"depth_cm": round(depth), "band": band_for(depth), "confidence": conf, "reference": ref.label}


def run(image: bytes, vision: VisionProvider) -> dict:
    seg = vision.segment(image, PROMPTS)
    out = estimate(seg)
    out["masks"] = [{"label": m.label, "bbox": m.bbox, "score": round(m.score, 2)} for m in seg.masks]
    return out
