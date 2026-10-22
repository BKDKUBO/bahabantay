"""Depth estimation from segmentation masks using typical reference heights.

Returns band "cant_tell" (depth None) instead of guessing when there is no
reference object or confidence is below MIN_CONFIDENCE.
"""
from __future__ import annotations
from .providers.base import Segmentation, VisionProvider

REF_HEIGHT_CM = {"person": 160, "door": 210, "car_tire": 65, "jeepney": 200, "curb": 15}
PROMPTS = ["water", *REF_HEIGHT_CM.keys()]
MIN_CONFIDENCE = 0.55
BANDS = ["none", "ankle", "knee", "waist", "chest"]


def band_for(cm: float | None) -> str:
    if cm is None: return "cant_tell"
    if cm < 3: return "none"
    if cm < 20: return "ankle"
    if cm < 55: return "knee"
    if cm < 110: return "waist"
    return "chest"


def passability(cm: float) -> str:
    if cm < 25: return "all"
    if cm < 60: return "trucks"
    return "boats"


def cant_tell(reason: str, conf: float = 0.0, ref=None) -> dict:
    return {"depth_cm": None, "band": "cant_tell", "confidence": conf, "reference": ref, "reason": reason}


def estimate(seg: Segmentation) -> dict:
    water = max(seg.of("water"), key=lambda m: m.score, default=None)
    refs = [m for m in seg.masks if m.label in REF_HEIGHT_CM]
    if not refs:
        return cant_tell("no_reference")
    ref = max(refs, key=lambda m: m.score)
    conf = round(ref.score * (water.score if water else 0.9), 2)
    if conf < MIN_CONFIDENCE:
        return cant_tell("low_confidence", conf, ref.label)
    x0, top, x1, bottom = ref.bbox
    if water is None:
        depth = 0.0
    else:
        waterline = max(top, min(bottom, water.bbox[1]))
        depth = (bottom - waterline) / (bottom - top) * REF_HEIGHT_CM[ref.label]
    return {"depth_cm": round(depth), "band": band_for(depth), "confidence": conf, "reference": ref.label, "reason": None}


def from_answer(reference: str, submerged_pct: float) -> dict:
    """Re-estimate from a reporter's follow-up answer (object + how much is under water)."""
    if reference not in REF_HEIGHT_CM or not 0 <= submerged_pct <= 100:
        raise ValueError("bad answer")
    d = REF_HEIGHT_CM[reference] * submerged_pct / 100
    return {"depth_cm": round(d), "band": band_for(d), "confidence": 0.6, "reference": reference, "reason": "reporter_answer"}


def run(image: bytes, vision: VisionProvider) -> dict:
    seg = vision.segment(image, PROMPTS)
    out = estimate(seg)
    out["masks"] = [{"label": m.label, "bbox": m.bbox, "score": round(m.score, 2)} for m in seg.masks]
    return out
