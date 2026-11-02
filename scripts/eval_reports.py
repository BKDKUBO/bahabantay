"""Prototype eval of text extraction, severity and incident grouping on a SYNTHETIC labeled set.

  python -m scripts.eval_reports            # mock (keyword rules), always
  python -m scripts.eval_reports --meta     # Muse Spark extraction (needs META_API_KEY; fallback disabled)
Writes docs/eval/reports_<provider>.md. Numbers are synthetic prototype results, not field accuracy.
"""
import argparse, json, os, sys, time
from datetime import datetime, timedelta, timezone
from itertools import combinations
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import assess
from app.providers.mock import MockReports

SET = ROOT / "sample_data" / "eval" / "reports_synthetic.json"
T0 = datetime(2026, 11, 2, tzinfo=timezone.utc)


def run(items, reporter):
    rows, t = [], time.time()
    for it in items:
        ext = reporter.extract(it["note"], {})
        sev = assess.severity(ext["water_level"], ext["hazards"], ext["people_at_risk"])
        rows.append((it, ext, sev))
    ms = int((time.time() - t) * 1000 / max(1, len(items)))
    lab = lambda it: it["label"]
    n = len(rows)
    lvl = sum(e["water_level"] == lab(it)["water_level"] for it, e, _ in rows)
    ppl = sum(e["people_at_risk"] == lab(it)["people_at_risk"] for it, e, _ in rows)
    tp = sum(len(set(e["hazards"]) & set(lab(it)["hazards"])) for it, e, _ in rows)
    fp = sum(len(set(e["hazards"]) - set(lab(it)["hazards"])) for it, e, _ in rows)
    fn = sum(len(set(lab(it)["hazards"]) - set(e["hazards"])) for it, e, _ in rows)
    sev_ok = sum(s == lab(it)["severity"] for it, _, s in rows)
    crit = [(it, s) for it, _, s in rows if lab(it)["severity"] == "critical"]
    # grouping: pairwise agreement of predicted incident vs labeled group
    reps = [{"id": i, "reported_at": (T0 + timedelta(minutes=it["min"])).isoformat(), "barangay": it["barangay"], "street": it["street"],
             "lat": 14.65 + i * 0.001, "lng": 121.1, "kind": "flood", "duplicate_of": None} for i, (it, _, _) in enumerate(rows)]
    pred = {}
    for k, rs in assess.group(reps).items():
        for r in rs: pred[r["id"]] = k
    pairs = list(combinations(range(n), 2))
    same_l = {(a, b) for a, b in pairs if rows[a][0]["label"]["group"] == rows[b][0]["label"]["group"]}
    same_p = {(a, b) for a, b in pairs if pred[a] == pred[b]}
    g_acc = sum(((a, b) in same_l) == ((a, b) in same_p) for a, b in pairs) / len(pairs)
    g_p = len(same_l & same_p) / len(same_p) if same_p else 1.0
    g_r = len(same_l & same_p) / len(same_l) if same_l else 1.0
    return {"n": n, "water_level_acc": lvl / n, "people_at_risk_acc": ppl / n,
            "hazard_precision": tp / (tp + fp) if tp + fp else 1.0, "hazard_recall": tp / (tp + fn) if tp + fn else 1.0,
            "severity_agreement": sev_ok / n, "critical_recall": sum(s == "critical" for _, s in crit) / len(crit),
            "group_pair_acc": g_acc, "group_precision": g_p, "group_recall": g_r, "ms_per_item": ms, "rows": rows}


def write_md(res, provider, out):
    pct = lambda x: f"{x:.0%}"
    L = [f"# Report-understanding eval ({provider})", "",
         f"**Data:** `sample_data/eval/reports_synthetic.json`, {res['n']} **synthetic** Filipino / English / Taglish text reports "
         "written and labeled by the team. Prototype eval only: not real reports, not field accuracy, and labels share the authors' bias.", "",
         "| Metric | Result |", "|---|---|",
         f"| Water level extracted correctly | {pct(res['water_level_acc'])} |",
         f"| People-at-risk flag correct | {pct(res['people_at_risk_acc'])} |",
         f"| Hazard precision / recall | {pct(res['hazard_precision'])} / {pct(res['hazard_recall'])} |",
         f"| Severity agreement with team label | {pct(res['severity_agreement'])} |",
         f"| Critical cases caught (recall) | {pct(res['critical_recall'])} |",
         f"| Duplicate grouping, pairwise accuracy | {pct(res['group_pair_acc'])} (precision {pct(res['group_precision'])}, recall {pct(res['group_recall'])}) |",
         f"| Avg extraction time per report | {res['ms_per_item']} ms |", "",
         "Severity = deterministic rules in `app/assess.py` applied to the extracted fields. Grouping = `assess.group` (same barangay + street or within 60 m, within 90 min).", "",
         "| ID | Note | Level (label → got) | Hazards got | Severity (label → got) |", "|---|---|---|---|---|"]
    for it, e, s in res["rows"]:
        lb = it["label"]
        L.append(f"| {it['id']} | {it['note']} | {lb['water_level']} → {e['water_level']}{'' if lb['water_level']==e['water_level'] else ' ✗'} | "
                 f"{', '.join(e['hazards']) or '–'} | {lb['severity']} → {s}{'' if lb['severity']==s else ' ✗'} |")
    out.write_text("\n".join(L) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("--meta", action="store_true"); a = ap.parse_args(argv)
    items = json.loads(SET.read_text())["items"]
    if a.meta:
        os.environ["BAHABANTAY_META_FALLBACK"] = "false"   # a failed call must fail, not silently score the mock
        from app.providers.meta import MetaReports; reporter, name = MetaReports(), "meta"
    else:
        reporter, name = MockReports(), "mock"
    res = run(items, reporter)
    write_md(res, "Muse Spark" if a.meta else "keyword rules (mock)", ROOT / "docs" / "eval" / f"reports_{name}.md")
    print(name, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in res.items() if k != "rows"})
    return res


if __name__ == "__main__":
    main()
