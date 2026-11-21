"""LangGraph nodes. Each takes the state (or a Send payload) and returns a partial update."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

from . import config, prompts
from .llm import call
from .parser import load_show, sec_to_ts
from .schemas import CandidatePromo, EpisodeCandidates, Judgement
from .timing import clip_text, index_beats, overlap_iou, repair, resolve, segment_beats

log = logging.getLogger("promo_finder")


# ---------------------------------------------------------------- 1. load (code)
def load(state):
    show = state.get("show") or load_show(state["source"])
    if not show:
        raise ValueError(f"No episodes found in {state.get('source')}")
    log.info("Loaded %d episodes, %d beats", len(show), sum(len(e.beats) for e in show.values()))
    return {"show": show, "refine_round": 0}


# ---------------------------------------------------------------- 2. find per episode (LLM, fan-out)
def _context(show, n: int) -> str:
    first = show[min(show)]
    prev = [show[k] for k in sorted(show) if n - 3 <= k < n]
    lines = [f"Premise (ep {first.number}): {first.logline}"]
    lines += [f"Ep {e.number}: {e.logline}" for e in prev if e.number != first.number]
    if show[n].continuity:
        lines.append(f"Continuity: {show[n].continuity}")
    return "\n".join(lines)


def find_in_episode(payload):
    show, n = payload["show"], payload["episode"]
    ep = show[n]
    try:
        res: EpisodeCandidates = call(
            "finder", EpisodeCandidates,
            prompts.FINDER_SYSTEM.format(n=config.PROMOS_PER_EPISODE),
            prompts.FINDER_USER.format(context=_context(show, n), episode=n,
                                       duration=sec_to_ts(ep.duration), logline=ep.logline,
                                       transcript=ep.transcript(config.INCLUDE_CAMERA)))
    except Exception as exc:  # one bad episode must not kill a 50-episode run
        log.warning("Episode %s failed: %s", n, exc)
        return {"failures": [{"stage": "find", "episode": n, "error": repr(exc)}]}
    cands = []
    for i, p in enumerate(res.promos[: config.PROMOS_PER_EPISODE + 1]):
        d = p.model_dump()
        d.update(cid=f"E{n:02d}-P{i + 1}", source="episode", attempts=0)
        cands.append(d)
    return {"candidates": cands}


# ---------------------------------------------------------------- 3. stitch across episodes (LLM)
def stitch(state):
    show, cands = state["show"], list(state.get("candidates", []))
    beats = index_beats(show)
    pending = list(cands)
    if config.STITCHED_PROMOS <= 0 or len(show) < 2 or not cands:
        return {"pending": pending}
    pool = sorted(cands, key=lambda c: -c.get("self_score", 0))[: config.STITCH_POOL]
    blocks = []
    for c in pool:
        lines = [b.render() for s in c["segments"] for b in segment_beats(s, show, beats) if b.kind != "camera"]
        blocks.append(f"### {c['cid']} - {c['title']} (hook: {c['hook']}; cliffhanger: {c['cliffhanger']})\n"
                      + "\n".join(lines))
    loglines = "\n".join(f"Ep {e.number}: {e.logline}" for e in show.values())
    try:
        res: EpisodeCandidates = call(
            "finder", EpisodeCandidates,
            prompts.STITCH_SYSTEM.format(n=config.STITCHED_PROMOS),
            prompts.STITCH_USER.format(loglines=loglines, candidates="\n\n".join(blocks)))
    except Exception as exc:
        log.warning("Stitch failed: %s", exc)
        return {"pending": pending, "failures": [{"stage": "stitch", "error": repr(exc)}]}
    stitched = []
    for i, p in enumerate(res.promos[: config.STITCHED_PROMOS]):
        d = p.model_dump()
        d.update(cid=f"X-P{i + 1}", source="stitch", attempts=0)
        stitched.append(d)
    return {"candidates": stitched, "pending": pending + stitched}


# ---------------------------------------------------------------- 4. validate (code) + route
def validate(state):
    beats = index_beats(state["show"])
    ok, bad = [], []
    for c in state.get("pending", []):
        p = resolve(repair(c, beats), state["show"], beats)
        (ok if p["valid"] else bad).append(p)
    log.info("Validate round %s: %d ok, %d need fixing", state.get("refine_round", 0), len(ok), len(bad))
    return {"valid": ok, "pending": bad}


def route_after_validate(state):
    if state.get("pending") and state.get("refine_round", 0) < config.MAX_REFINE_ROUNDS:
        return "refine"
    return "dedupe"


# ---------------------------------------------------------------- 5. refine (LLM)
def _refine_one(p, show):
    eps = sorted({s.get("episode") for s in p["segments"] if s.get("episode") in show}) or [
        int(p["cid"][1:3]) if p["cid"].startswith("E") else min(show)]
    transcript = "\n\n".join(f"EPISODE {n}:\n{show[n].transcript(config.INCLUDE_CAMERA)}" for n in eps)
    timing = ", ".join(f"seg{i + 1}: E{s.get('episode')} {s.get('start_ts', '?')}-{s.get('end_ts', '?')}"
                       for i, s in enumerate(p["segments"])) + f" | total {p.get('duration', 0):.1f}s"
    promo = {k: p[k] for k in ("title", "segments", "hook_beat", "cliffhanger_beat", "hook", "cliffhanger", "why")}
    promo["segments"] = [{k: s[k] for k in ("episode", "start_beat", "end_beat")} for s in p["segments"]]
    try:
        fixed: CandidatePromo = call("finder", CandidatePromo, prompts.REFINE_SYSTEM,
                                     prompts.REFINE_USER.format(errors="\n".join(p["errors"]),
                                                                promo=json.dumps(promo, indent=1),
                                                                timing=timing, transcript=transcript))
    except Exception as exc:
        log.warning("Refine %s failed: %s", p["cid"], exc)
        return p
    d = fixed.model_dump()
    d.update(cid=p["cid"], source=p["source"], attempts=p.get("attempts", 0) + 1,
             previous_errors=p["errors"])
    return d


def refine(state):
    show = state["show"]
    with ThreadPoolExecutor(max_workers=config.MAX_CONCURRENCY) as ex:
        fixed = list(ex.map(lambda p: _refine_one(p, show), state["pending"]))
    return {"pending": fixed, "refine_round": state.get("refine_round", 0) + 1}


# ---------------------------------------------------------------- 6. dedupe (code)
def dedupe(state):
    show = state["show"]
    beats = index_beats(show)
    rejected = [dict(p, reject_reason="failed checks after refine") for p in state.get("pending", [])]
    kept = []
    for p in sorted(state.get("valid", []), key=lambda x: -x.get("self_score", 0)):
        dup = next((k for k in kept if overlap_iou(p, k) >= config.DEDUPE_IOU), None)
        if dup:
            rejected.append(dict(p, reject_reason=f"duplicate of {dup['cid']}"))
            continue
        p["clip_text"] = clip_text(p, show, beats)
        kept.append(p)
    for p in kept[config.MAX_JUDGED:]:
        rejected.append(dict(p, reject_reason=f"not judged: beyond MAX_JUDGED={config.MAX_JUDGED}"))
    kept = kept[: config.MAX_JUDGED]
    log.info("Dedupe: %d unique promos to judge, %d rejected", len(kept), len(rejected))
    return {"deduped": kept, "rejected": rejected}


# ---------------------------------------------------------------- 7. judge (LLM, fan-out)
def judge_one(payload):
    p = dict(payload["promo"])
    try:
        j: Judgement = call("judge", Judgement, prompts.JUDGE_SYSTEM,
                            prompts.JUDGE_USER.format(duration=p["duration"], n_segments=len(p["segments"]),
                                                      clip=p["clip_text"], hook=p["hook"],
                                                      cliffhanger=p["cliffhanger"]))
        p["judge"] = j.model_dump()
    except Exception as exc:
        log.warning("Judge %s failed: %s", p["cid"], exc)
        p["judge"] = None
        return {"judged": [p], "failures": [{"stage": "judge", "cid": p["cid"], "error": repr(exc)}]}
    return {"judged": [p]}
