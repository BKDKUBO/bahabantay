"""Run the depth estimator over a labeled set; write docs/eval/results.md.

Default set is SIMULATED (sample_data/eval/labeled_simulated.json). Numbers on
it only check the math; they say nothing about accuracy on real photos.
"""
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.depth import BANDS, band_for, estimate
from app.providers.base import Mask, Segmentation


def evaluate(items):
    rows = []
    for it in items:
        seg = Segmentation([Mask(m["label"], tuple(m["bbox"]), m["score"]) for m in it["masks"]])
        est = estimate(seg); rows.append((it, est))
    told = [(it, e) for it, e in rows if e["band"] != "cant_tell"]
    mae = round(sum(abs(e["depth_cm"] - it["true_depth_cm"]) for it, e in told) / len(told), 1) if told else None
    per = {}
    for b in BANDS:
        sel = [(it, e) for it, e in told if band_for(it["true_depth_cm"]) == b]
        per[b] = {"n": len(sel), "correct": sum(e["band"] == b for _, e in sel)}
    return {"n": len(rows), "cant_tell": len(rows) - len(told), "cant_tell_rate": round((len(rows) - len(told)) / len(rows), 2),
            "mae_cm": mae, "level_accuracy": round(sum(v["correct"] for v in per.values()) / len(told), 2) if told else None,
            "per_level": per, "rows": rows}


def write_md(res, src, out):
    L = ["# Depth estimator eval", "", f"**Data:** `{src}` — **SIMULATED** synthetic masks with known depths. "
         "These numbers only check the depth math and can't-tell logic. They are NOT real-world accuracy. "
         "Replace with real flood photos with tape-measured depths before quoting any figure.", "",
         f"- Items: {res['n']}", f"- Mean absolute error (excluding can't tell): **{res['mae_cm']} cm**",
         f"- Level accuracy (excluding can't tell): **{res['level_accuracy']:.0%}**",
         f"- Can't tell rate: **{res['cant_tell_rate']:.0%}** ({res['cant_tell']} of {res['n']})", "",
         "| Level | Items | Correct |", "|---|---|---|"]
    L += [f"| {b} | {v['n']} | {v['correct']} |" for b, v in res["per_level"].items()]
    L += ["", "| ID | Ref | True cm | Est cm | Est level | Note |", "|---|---|---|---|---|---|"]
    for it, e in res["rows"]:
        L.append(f"| {it['id']} | {it['reference']} | {it['true_depth_cm']} | {e['depth_cm'] if e['depth_cm'] is not None else '–'} | {e['band']} | {e.get('reason') or ''} |")
    out.parent.mkdir(parents=True, exist_ok=True); out.write_text("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--set", default=str(ROOT / "sample_data/eval/labeled_simulated.json"))
    ap.add_argument("--out", default=str(ROOT / "docs/eval/results.md")); a = ap.parse_args()
    res = evaluate(json.loads(Path(a.set).read_text())["items"]); write_md(res, Path(a.set).relative_to(ROOT) if Path(a.set).is_relative_to(ROOT) else a.set, Path(a.out))
    print(f"n={res['n']} MAE={res['mae_cm']}cm level_acc={res['level_accuracy']} cant_tell={res['cant_tell_rate']} (SIMULATED)")


if __name__ == "__main__":
    main()
