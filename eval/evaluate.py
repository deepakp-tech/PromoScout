"""Compare a run's promos against your hand-labelled gold promos (and, optionally, an editor review).

    python eval/evaluate.py outputs/<run>/promos.json eval/gold.json
    python eval/evaluate.py outputs/<run>/promos.json eval/gold.json --review outputs/<run>/review_sheet.csv

Matching: a predicted promo "finds" a gold promo when their time IoU >= --iou (default 0.3,
because two good editors rarely pick the exact same frames).
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promo_finder.parser import ts_to_sec  # noqa: E402
from promo_finder.timing import overlap_iou  # noqa: E402


def norm(p):
    segs = [{"episode": s["episode"],
             "start": s["start"] if isinstance(s.get("start"), (int, float)) else ts_to_sec(s["start"]),
             "end": s["end"] if isinstance(s.get("end"), (int, float)) else ts_to_sec(s["end"])}
            for s in p["segments"]]
    return {**p, "segments": segs, "duration": sum(s["end"] - s["start"] for s in segs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pred")
    ap.add_argument("gold")
    ap.add_argument("--iou", type=float, default=0.3)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--review", help="filled review_sheet.csv")
    a = ap.parse_args()

    pred = [norm(p) for p in json.loads(Path(a.pred).read_text())]
    gold = [norm(g) for g in json.loads(Path(a.gold).read_text())]
    gold_eps = {s["episode"] for g in gold for s in g["segments"]}
    pred_in_scope = [p for p in pred if all(s["episode"] in gold_eps for s in p["segments"])]

    lines = [f"# Evaluation of {a.pred}", "",
             f"Gold promos: {len(gold)} over episodes {sorted(gold_eps)}",
             f"Predicted promos in those episodes: {len(pred_in_scope)} (of {len(pred)} total)",
             f"Match rule: time IoU >= {a.iou}", "", "## Per gold promo", "",
             "| gold | best match | IoU | its rank |", "|---|---|---|---|"]
    found = 0
    for g in gold:
        best = max(pred_in_scope, key=lambda p: overlap_iou(g, p), default=None)
        iou = overlap_iou(g, best) if best else 0
        found += iou >= a.iou
        lines.append(f"| {g['id']} | {best['cid'] if best else '-'} | {iou:.2f} | {best['rank'] if best else '-'} |")
    recall = found / len(gold) if gold else 0
    topk = sorted(pred_in_scope, key=lambda p: p["rank"])[: a.k]
    prec = sum(any(overlap_iou(p, g) >= a.iou for g in gold) for p in topk) / len(topk) if topk else 0
    lines += ["", "## Summary", "",
              f"- Recall (gold promos the tool found): **{found}/{len(gold)} = {recall:.0%}**",
              f"- Precision@{a.k} within gold episodes (top picks that match a gold promo): **{prec:.0%}**",
              "  (low precision is not always bad - the tool may find good promos you did not label; "
              "check them by hand)"]

    if a.review:
        rows = list(csv.DictReader(open(a.review)))
        marked = [r for r in rows if r.get("editor_would_post (y/n)", "").strip()]
        if marked:
            yes = [r for r in marked if r["editor_would_post (y/n)"].strip().lower().startswith("y")]
            top = [r for r in marked if int(r["rank"]) <= a.k]
            top_yes = [r for r in top if r["editor_would_post (y/n)"].strip().lower().startswith("y")]
            lines += [f"- Editor approval overall: {len(yes)}/{len(marked)} = {len(yes)/len(marked):.0%}",
                      f"- Editor approval in top {a.k}: {len(top_yes)}/{len(top) or 1} = "
                      f"{len(top_yes)/(len(top) or 1):.0%}"]

    report = "\n".join(lines)
    out = Path(a.pred).with_name("eval_report.md")
    out.write_text(report)
    print(report)
    print(f"\nSaved -> {out}")


if __name__ == "__main__":
    main()
