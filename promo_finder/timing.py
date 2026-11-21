"""Pure-code promo checks: beat IDs -> timestamps, rule validation, automatic repair, overlap.

Everything here is deterministic and free, so it runs on every candidate before any judge call.
"""
from __future__ import annotations

import copy

from . import config
from .parser import Beat, Episode, sec_to_ts


def index_beats(show: dict[int, Episode]) -> dict[str, Beat]:
    return {b.id: b for e in show.values() for b in e.beats}


def _ep_of(beat_id: str) -> int | None:
    try:
        return int(beat_id.split("-")[0].lstrip("E"))
    except (ValueError, IndexError):
        return None


def segment_beats(seg: dict, show: dict[int, Episode], beats: dict[str, Beat]) -> list[Beat]:
    a, b = beats.get(seg["start_beat"]), beats.get(seg["end_beat"])
    if not a or not b or a.episode != b.episode:
        return []
    lo, hi = sorted((a.idx, b.idx))
    return show[a.episode].beats[lo:hi + 1]


def repair(cand: dict, beats: dict[str, Beat]) -> dict:
    """Cheap code fixes before bothering the LLM: fix episode numbers, reversed ranges,
    a hook that starts too late, and a tail that runs past the cliffhanger."""
    c = copy.deepcopy(cand)
    for s in c["segments"]:
        ep = _ep_of(s["start_beat"])
        if ep:
            s["episode"] = ep
        a, b = beats.get(s["start_beat"]), beats.get(s["end_beat"])
        if a and b and a.episode == b.episode and a.idx > b.idx:
            s["start_beat"], s["end_beat"] = s["end_beat"], s["start_beat"]
    if not c["segments"]:
        return c
    hook, cliff = beats.get(c["hook_beat"]), beats.get(c["cliffhanger_beat"])
    first, last = c["segments"][0], c["segments"][-1]
    fa, fb = beats.get(first["start_beat"]), beats.get(first["end_beat"])
    if hook and fa and fb and hook.episode == fa.episode and fa.idx <= hook.idx <= fb.idx:
        if hook.start - fa.start > config.HOOK_WINDOW_SEC:
            first["start_beat"] = hook.id            # start the clip right on the hook
    la, lb = beats.get(last["start_beat"]), beats.get(last["end_beat"])
    if cliff and la and lb and cliff.episode == la.episode and la.idx <= cliff.idx <= lb.idx:
        if lb.end - cliff.end > config.CLIFF_TAIL_SEC:
            last["end_beat"] = cliff.id              # cut right on the cliffhanger
    return c


def resolve(cand: dict, show: dict[int, Episode], beats: dict[str, Beat]) -> dict:
    """Attach real timestamps + rule errors to a candidate."""
    p = copy.deepcopy(cand)
    errors: list[str] = []
    total = 0.0
    segs = p.get("segments", [])
    if not segs:
        errors.append("promo has no segments")
    if len(segs) > config.MAX_SEGMENTS:
        errors.append(f"{len(segs)} segments; max is {config.MAX_SEGMENTS}")
    for i, s in enumerate(segs):
        a, b = beats.get(s["start_beat"]), beats.get(s["end_beat"])
        if not a or not b:
            errors.append(f"segment {i+1}: unknown beat id {s['start_beat'] if not a else s['end_beat']}")
            continue
        if a.episode != b.episode:
            errors.append(f"segment {i+1}: start and end beats are in different episodes")
            continue
        s["episode"] = a.episode
        s["start"], s["end"] = a.start, max(b.end, a.start)
        s["start_ts"], s["end_ts"] = sec_to_ts(s["start"]), sec_to_ts(s["end"])
        dur = s["end"] - s["start"]
        if dur < config.MIN_SEGMENT_SEC:
            errors.append(f"segment {i+1} is only {dur:.1f}s")
        total += dur
    # overlapping segments
    timed = [s for s in segs if "start" in s]
    for i in range(len(timed)):
        for j in range(i + 1, len(timed)):
            x, y = timed[i], timed[j]
            if x["episode"] == y["episode"] and x["start"] < y["end"] and y["start"] < x["end"]:
                errors.append("segments overlap each other")
    p["duration"] = round(total, 2)
    if timed and not errors:
        if total < config.MIN_SEC:
            errors.append(f"too short: {total:.1f}s (min {config.MIN_SEC:.0f}s) - extend the clip")
        if total > config.MAX_SEC:
            errors.append(f"too long: {total:.1f}s (max {config.MAX_SEC:.0f}s) - trim it")
        hook, cliff = beats.get(p.get("hook_beat", "")), beats.get(p.get("cliffhanger_beat", ""))
        first, last = timed[0], timed[-1]
        if not hook:
            errors.append(f"unknown hook beat {p.get('hook_beat')}")
        elif not (hook.episode == first["episode"] and first["start"] <= hook.start <= first["end"]):
            errors.append("hook beat is not inside the first segment")
        elif hook.start - first["start"] > config.HOOK_WINDOW_SEC:
            errors.append(f"hook starts {hook.start - first['start']:.1f}s in; must be within "
                          f"{config.HOOK_WINDOW_SEC:.0f}s")
        if not cliff:
            errors.append(f"unknown cliffhanger beat {p.get('cliffhanger_beat')}")
        elif not (cliff.episode == last["episode"] and last["start"] <= cliff.start <= last["end"]):
            errors.append("cliffhanger beat is not inside the last segment")
        elif last["end"] - cliff.end > config.CLIFF_TAIL_SEC:
            errors.append(f"clip runs {last['end'] - cliff.end:.1f}s past the cliffhanger")
    p["errors"] = errors
    p["valid"] = not errors
    return p


def clip_text(p: dict, show: dict[int, Episode], beats: dict[str, Beat], include_camera: bool = True) -> str:
    """The clip as a stranger would experience it, with clip-relative time."""
    out, offset = [], 0.0
    for i, s in enumerate(p["segments"]):
        if i:
            out.append("--- CUT ---")
        seg_start = beats[s["start_beat"]].start
        for b in segment_beats(s, show, beats):
            if b.kind == "camera" and not include_camera:
                continue
            rel = offset + b.start - seg_start
            body = f'{b.speaker} ({b.tone}): {b.text}' if b.kind == "dialogue" else f"<{b.kind.upper()}> {b.text}"
            out.append(f"[+{rel:05.1f}s] {body}")
        offset += s.get("end", seg_start) - seg_start
    return "\n".join(out)


def overlap_iou(p: dict, q: dict) -> float:
    """Time IoU between two promos (only same-episode intervals can overlap)."""
    def ivs(x):
        return [(s["episode"], s["start"], s["end"]) for s in x["segments"] if "start" in s]
    inter = 0.0
    for e1, a1, b1 in ivs(p):
        for e2, a2, b2 in ivs(q):
            if e1 == e2:
                inter += max(0.0, min(b1, b2) - max(a1, a2))
    union = p.get("duration", 0) + q.get("duration", 0) - inter
    return inter / union if union > 0 else 0.0
