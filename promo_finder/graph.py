"""The LangGraph workflow.

    START -> load -> [Send: find_in_episode x N episodes] -> stitch -> validate
          validate --(errors & rounds left)--> refine -> validate
          validate --(all ok / out of rounds)--> dedupe -> [Send: judge_one x M promos] -> rank -> report -> END
"""
from __future__ import annotations

import operator
import time
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from . import config, nodes
from .llm import model_name
from .rank import rank_promos
from .report import write_outputs


class State(TypedDict, total=False):
    source: str
    out_dir: str
    started: float
    show: dict[int, Any]
    candidates: Annotated[list, operator.add]   # every LLM proposal (merged from parallel branches)
    pending: list                                # candidates waiting for validation / refinement
    valid: Annotated[list, operator.add]
    refine_round: int
    deduped: list
    rejected: list
    judged: Annotated[list, operator.add]
    ranked: list
    failures: Annotated[list, operator.add]
    first_pass_valid: int


def fan_out_episodes(state: State):
    return [Send("find_in_episode", {"show": state["show"], "episode": n}) for n in state["show"]]


def fan_out_judge(state: State):
    if not state.get("deduped"):
        return "rank"
    return [Send("judge_one", {"promo": p}) for p in state["deduped"]]


def validate_and_count(state: State):
    upd = nodes.validate(state)
    if state.get("refine_round", 0) == 0:
        upd["first_pass_valid"] = len(upd["valid"])
    return upd


def rank(state: State):
    show = state["show"]
    return {"ranked": rank_promos(list(state.get("judged", [])), len(show), min(show))}


def report(state: State):
    show = state["show"]
    n_cands = len(state.get("candidates", []))
    meta = {
        "show": Path(state.get("source", "")).stem,
        "models": {"finder": model_name("finder"), "judge": model_name("judge")},
        "prompt_version": config.PROMPT_VERSION,
        "seconds": time.time() - state.get("started", time.time()),
        "counts": {
            "episodes": len(show), "candidates": n_cands, "ranked": len(state.get("ranked", [])),
            "rejected": len(state.get("rejected", [])), "failures": len(state.get("failures", [])),
            "first_pass_valid_rate": f"{state.get('first_pass_valid', 0) / n_cands:.0%}" if n_cands else "n/a",
            "refine_rounds": state.get("refine_round", 0),
        },
        "tokens": state.get("tokens"),
    }
    out = write_outputs(state["out_dir"], state.get("ranked", []), state.get("candidates", []),
                        state.get("rejected", []), state.get("failures", []), meta)
    return {"out_dir": str(out)}


def build_graph():
    g = StateGraph(State)
    g.add_node("load", nodes.load)
    g.add_node("find_in_episode", nodes.find_in_episode)
    g.add_node("stitch", nodes.stitch)
    g.add_node("validate", validate_and_count)
    g.add_node("refine", nodes.refine)
    g.add_node("dedupe", nodes.dedupe)
    g.add_node("judge_one", nodes.judge_one)
    g.add_node("rank", rank)
    g.add_node("report", report)

    g.add_edge(START, "load")
    g.add_conditional_edges("load", fan_out_episodes, ["find_in_episode"])
    g.add_edge("find_in_episode", "stitch")
    g.add_edge("stitch", "validate")
    g.add_conditional_edges("validate", nodes.route_after_validate, ["refine", "dedupe"])
    g.add_edge("refine", "validate")
    g.add_conditional_edges("dedupe", fan_out_judge, ["judge_one", "rank"])
    g.add_edge("judge_one", "rank")
    g.add_edge("rank", "report")
    g.add_edge("report", END)
    return g.compile()


def run(source: str, out_dir: str, show=None, on_update=None) -> dict:
    """Run the full pipeline. on_update(node_name, update) gets streaming progress (used by the UI)."""
    app = build_graph()
    init: State = {"source": str(source), "out_dir": str(out_dir), "started": time.time()}
    if show is not None:
        init["show"] = show
    cfg = {"max_concurrency": config.MAX_CONCURRENCY, "recursion_limit": 100}
    try:
        from langchain_core.callbacks import get_usage_metadata_callback
        usage_cm = get_usage_metadata_callback()
    except ImportError:  # older langchain-core
        usage_cm = None

    def _stream():
        final = dict(init)
        for chunk in app.stream(init, config=cfg, stream_mode="updates"):
            for node, upd in chunk.items():
                if on_update:
                    on_update(node, upd)
                if upd:
                    final.update(upd)
        return final

    if usage_cm:
        with usage_cm as cb:
            final = _stream()
            final["tokens"] = cb.usage_metadata
        # re-write meta with token usage now that the run has finished
        meta_path = Path(final["out_dir"]) / "run_meta.json"
        if meta_path.exists():
            import json
            meta = json.loads(meta_path.read_text())
            meta["tokens"] = final["tokens"]
            meta_path.write_text(json.dumps(meta, indent=2, default=str))
    else:
        final = _stream()
    return final
