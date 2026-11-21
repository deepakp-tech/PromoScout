"""CLI entry point.

    python run.py data/show.zip
    python run.py "data/I Married a Broken Soldier" --episodes 1-10 --model groq:llama-3.3-70b-versatile
"""
import argparse
import logging
import os
import re
import time
from pathlib import Path


def parse_range(spec: str) -> set[int]:
    out = set()
    for part in spec.split(","):
        a, _, b = part.partition("-")
        out.update(range(int(a), int(b or a) + 1))
    return out


def main():
    ap = argparse.ArgumentParser(description="Find the best promos in a microdrama screenplay.")
    ap.add_argument("source", help="folder, .zip or single .txt of episode screenplays")
    ap.add_argument("--out", help="output folder (default outputs/<show>_<time>)")
    ap.add_argument("--model", help="provider:model for every step, e.g. google_genai:gemini-2.5-flash")
    ap.add_argument("--finder-model", help="model that proposes promos")
    ap.add_argument("--judge-model", help="model that scores promos")
    ap.add_argument("--episodes", help="subset, e.g. 1-10 or 1,4,7")
    ap.add_argument("--no-stitch", action="store_true", help="skip cross-episode stitched promos")
    args = ap.parse_args()

    # env must be set before promo_finder.config is imported
    if args.model:
        os.environ["MODEL"] = args.model
    if args.finder_model:
        os.environ["MODEL_FINDER"] = args.finder_model
    if args.judge_model:
        os.environ["MODEL_JUDGE"] = args.judge_model
    if args.no_stitch:
        os.environ["STITCHED_PROMOS"] = "0"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    from promo_finder.graph import run
    from promo_finder.parser import load_show

    show = load_show(args.source)
    if args.episodes:
        keep = parse_range(args.episodes)
        show = {n: e for n, e in show.items() if n in keep}
    slug = re.sub(r"[^A-Za-z0-9]+", "_", Path(args.source).stem)[:40].strip("_")
    out = args.out or f"outputs/{slug}_{time.strftime('%Y%m%d_%H%M%S')}"

    def progress(node, upd):
        if node in ("find_in_episode", "judge_one"):
            return
        logging.info("finished node: %s", node)

    final = run(args.source, out, show=show, on_update=progress)
    print(f"\nDone. {len(final.get('ranked', []))} promos -> {final['out_dir']}/report.md")


if __name__ == "__main__":
    main()
