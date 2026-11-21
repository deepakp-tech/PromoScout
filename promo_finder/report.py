"""Writes the raw outputs folder: JSON, CSV, a readable Markdown report and an editor review sheet."""
from __future__ import annotations

import csv
import json
from pathlib import Path

KEEP = ("rank", "post_first", "score", "cid", "source", "title", "duration", "segments", "hook",
        "cliffhanger", "why", "rank_reason", "judge", "hook_beat", "cliffhanger_beat",
        "self_score", "attempts", "previous_errors", "clip_text")


def seg_str(p: dict) -> str:
    return " + ".join(f"Ep{s['episode']} {s['start_ts']}-{s['end_ts']}" for s in p["segments"])


def write_outputs(out_dir: str | Path, ranked, candidates, rejected, failures, meta) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    (out / "promos.json").write_text(json.dumps([{k: p.get(k) for k in KEEP} for p in ranked], indent=2))
    (out / "candidates_raw.json").write_text(json.dumps(candidates, indent=2))   # unedited LLM proposals
    (out / "rejected.json").write_text(json.dumps(
        [{k: p.get(k) for k in ("cid", "title", "segments", "duration", "errors", "reject_reason")}
         for p in rejected], indent=2))
    (out / "failures.json").write_text(json.dumps(failures, indent=2))
    (out / "run_meta.json").write_text(json.dumps(meta, indent=2, default=str))

    with open(out / "promos.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "post_first", "score", "id", "segments (episode start-end)", "duration_s",
                    "hook", "cliffhanger", "why_it_works", "why_this_rank", "verdict", "judge_issues"])
        for p in ranked:
            j = p.get("judge") or {}
            w.writerow([p["rank"], p["post_first"], p["score"], p["cid"], seg_str(p), p["duration"],
                        p["hook"], p["cliffhanger"], p["why"], p["rank_reason"], j.get("verdict"),
                        "; ".join(j.get("issues", []))])

    # human-in-the-loop sheet: the editor marks each promo, which becomes new eval data
    with open(out / "review_sheet.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "id", "segments", "hook", "cliffhanger", "editor_would_post (y/n)",
                    "better_start", "better_end", "notes"])
        for p in ranked:
            w.writerow([p["rank"], p["cid"], seg_str(p), p["hook"], p["cliffhanger"], "", "", "", ""])

    md = [f"# Promo report - {meta.get('show', '')}", "",
          f"Models: finder `{meta['models']['finder']}`, judge `{meta['models']['judge']}`  ",
          f"Episodes: {meta['counts']['episodes']} | candidates: {meta['counts']['candidates']} | "
          f"valid & unique: {meta['counts']['ranked']} | rejected: {meta['counts']['rejected']} | "
          f"first-pass rule pass rate: {meta['counts'].get('first_pass_valid_rate', 'n/a')}  ",
          f"Runtime: {meta.get('seconds', 0):.0f}s (token usage is in run_meta.json)", "",
          "## Post these first", ""]
    for p in ranked:
        if p["rank"] == len([q for q in ranked if q["post_first"]]) + 1:
            md += ["", "## Other valid promos", ""]
        j = p.get("judge") or {}
        md += [f"### {p['rank']}. {p['title']}  (`{p['cid']}`, score {p['score']}, {p['duration']:.1f}s)",
               f"- **Segments:** {seg_str(p)}",
               f"- **Hook:** {p['hook']}",
               f"- **Cliffhanger:** {p['cliffhanger']}",
               f"- **Why it works:** {p['why']}",
               f"- **Why this rank:** {p['rank_reason']}",
               f"- **Judge verdict:** {j.get('verdict')} - issues: {'; '.join(j.get('issues', [])) or 'none'}",
               ""]
    if rejected:
        md += ["## Rejected (shown for quality checking)", ""]
        for p in rejected:
            md.append(f"- `{p['cid']}` {p.get('title', '')}: {p.get('reject_reason')} "
                      f"{'- ' + '; '.join(p.get('errors', [])) if p.get('errors') else ''}")
    if failures:
        md += ["", "## Pipeline failures", ""] + [f"- {f}" for f in failures]
    (out / "report.md").write_text("\n".join(md))
    return out
