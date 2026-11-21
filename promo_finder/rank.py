"""Ranking = transparent formula in code (not an LLM), so editors can see and tune it."""
from __future__ import annotations

from . import config


def score(p: dict, n_episodes: int, first_ep: int = 1) -> float | None:
    j = p.get("judge")
    if not j:
        return None
    base = 10 * (config.W_HOOK * j["hook_score"] + config.W_CLIFF * j["cliffhanger_score"]
                 + config.W_STANDALONE * j["standalone_score"]
                 + config.W_SPOILER * (10 - j["spoiler_risk"]))
    earliest = min(s["episode"] for s in p["segments"])
    span = max(n_episodes - 1, 1)
    bonus = config.EARLY_EP_BONUS * (1 - (earliest - first_ep) / span)
    penalty = 30 if j["verdict"] == "reject" else 0
    return round(base + bonus - penalty, 1)


def _reason(p: dict) -> str:
    j = p["judge"]
    eps = sorted({s["episode"] for s in p["segments"]})
    bits = [f"hook {j['hook_score']}/10", f"cliffhanger {j['cliffhanger_score']}/10",
            f"standalone {j['standalone_score']}/10"]
    if j["spoiler_risk"] >= 6:
        bits.append(f"spoiler risk {j['spoiler_risk']}/10")
    where = f"ep {eps[0]}" if len(eps) == 1 else f"eps {', '.join(map(str, eps))}"
    early = " - early episode, so new viewers land at the start of the story" if eps[0] <= 5 else ""
    return f"{', '.join(bits)}; from {where}{early}"


def rank_promos(promos: list[dict], n_episodes: int, first_ep: int = 1) -> list[dict]:
    for p in promos:
        p["score"] = score(p, n_episodes, first_ep)
        p["rank_reason"] = _reason(p) if p.get("judge") else "not judged (judge call failed)"
    ordered = sorted(promos, key=lambda p: (p["score"] is None, -(p["score"] or 0)))
    # Posting order: best first, but spread across episodes and never reuse the same hook beat.
    top, rest, per_ep, hooks = [], [], {}, set()
    for p in ordered:
        ep = p["segments"][0]["episode"]
        ok = (len(top) < config.TOP_N and p["score"] is not None
              and per_ep.get(ep, 0) < config.MAX_PER_EPISODE_IN_TOP and p["hook_beat"] not in hooks
              and p["judge"]["verdict"] != "reject")
        if ok:
            top.append(p)
            per_ep[ep] = per_ep.get(ep, 0) + 1
            hooks.add(p["hook_beat"])
        else:
            rest.append(p)
    final = top + rest
    for i, p in enumerate(final, 1):
        p["rank"] = i
        p["post_first"] = i <= len(top)
    return final
