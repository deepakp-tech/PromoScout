"""Offline end-to-end test with a FAKE model (no API key, no cost).

It checks the plumbing - parsing, fan-out, validation, auto-repair, the refine loop, dedupe,
ranking and output files - not promo quality.

    python tests/test_offline.py path/to/show.zip
"""
import hashlib
import json
import random
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from promo_finder import llm  # noqa: E402
from promo_finder.parser import ts_to_sec  # noqa: E402
from promo_finder.schemas import CandidatePromo, EpisodeCandidates, Judgement  # noqa: E402

BEAT = re.compile(r"\[(E(\d+)-B\d+) ([\d:.]+)-([\d:.]+)\] (.*)")


def _beats(text):
    return [dict(id=m[1], ep=int(m[2]), s=ts_to_sec(m[3]), e=ts_to_sec(m[4]), body=m[5])
            for m in BEAT.finditer(text)]


def _promo(bs, rng, length, title="fake"):
    """Pick a hook ('!' line) and a cliffhanger ('?' line) about `length` seconds later."""
    hooks = [b for b in bs if "!" in b["body"]] or bs
    h = rng.choice(hooks[: max(1, len(hooks) // 2)])
    later = [b for b in bs if b["ep"] == h["ep"] and b["s"] > h["s"]]
    end = min(later, key=lambda b: abs(b["e"] - h["s"] - length), default=h)
    return CandidatePromo(title=title, segments=[dict(episode=h["ep"], start_beat=h["id"], end_beat=end["id"])],
                          hook_beat=h["id"], cliffhanger_beat=end["id"], hook=h["body"][:80],
                          cliffhanger=end["body"][:80], why="fake model output", self_score=rng.randint(4, 9))


class FakeStructured:
    def __init__(self, schema):
        self.schema = schema

    def with_retry(self, **_):
        return self

    def invoke(self, messages):
        user = messages[-1][1]
        rng = random.Random(hashlib.md5(user.encode()).hexdigest())
        bs = _beats(user)
        if self.schema is EpisodeCandidates:
            # deliberately include one too-long promo to exercise refine
            return EpisodeCandidates(promos=[_promo(bs, rng, 35), _promo(bs, rng, 30), _promo(bs, rng, 90)])
        if self.schema is CandidatePromo:
            return _promo(bs, rng, 35, "refined")
        if self.schema is Judgement:
            s = lambda: rng.randint(3, 10)  # noqa: E731
            return Judgement(hook_score=s(), cliffhanger_score=s(), standalone_score=s(),
                             spoiler_risk=rng.randint(0, 7), verdict=rng.choice(["post", "maybe", "reject"]),
                             issues=["fake issue"])
        raise ValueError(self.schema)


class FakeChat:
    def __init__(self, name):
        self.name = name

    def with_structured_output(self, schema):
        return FakeStructured(schema)


def run_sequential(source, out_dir):
    """Same steps as graph.py, called in order - used when langgraph is not installed."""
    from promo_finder import config, nodes
    from promo_finder.rank import rank_promos
    from promo_finder.report import write_outputs

    s = {"source": source}
    s.update(nodes.load(s))
    s["candidates"], s["failures"] = [], []
    for n in s["show"]:
        u = nodes.find_in_episode({"show": s["show"], "episode": n})
        s["candidates"] += u.get("candidates", [])
        s["failures"] += u.get("failures", [])
    u = nodes.stitch(s)
    s["candidates"] += u.get("candidates", [])
    s["pending"], s["valid"] = u["pending"], []
    while True:
        u = nodes.validate(s)
        s["valid"] += u["valid"]
        s["pending"] = u["pending"]
        if nodes.route_after_validate(s) == "dedupe":
            break
        s.update(nodes.refine(s))
    s.update(nodes.dedupe(s))
    judged = [nodes.judge_one({"promo": p})["judged"][0] for p in s["deduped"]]
    ranked = rank_promos(judged, len(s["show"]), min(s["show"]))
    meta = {"show": "test", "models": {"finder": "fake", "judge": "fake"},
            "counts": {"episodes": len(s["show"]), "candidates": len(s["candidates"]), "ranked": len(ranked),
                       "rejected": len(s["rejected"])}, "seconds": 0}
    return write_outputs(out_dir, ranked, s["candidates"], s["rejected"], s["failures"], meta), ranked


def main(source):
    llm.set_model_factory(FakeChat)
    out = Path(tempfile.mkdtemp()) / "run"
    try:
        from promo_finder.graph import run
        final = run(source, str(out))
        ranked = final["ranked"]
        print("engine: langgraph")
    except ImportError:
        out, ranked = run_sequential(source, out)
        print("engine: sequential (langgraph not installed)")

    assert ranked, "no promos produced"
    for p in ranked:
        assert 20 <= p["duration"] <= 60, p["duration"]
        assert p["segments"][0]["start_ts"] and p["segments"][-1]["end_ts"]
    for f in ("promos.json", "promos.csv", "report.md", "candidates_raw.json", "rejected.json", "review_sheet.csv"):
        assert (Path(out) / f).exists(), f
    rejected = json.loads((Path(out) / "rejected.json").read_text())
    print(f"OK - {len(ranked)} valid promos, {len(rejected)} rejected, outputs in {out}")
    print((Path(out) / "report.md").read_text()[:1500])


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data")
