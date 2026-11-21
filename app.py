"""PromoScout (Streamlit UI): upload a show's episode scripts, get the best promo clips.

    streamlit run app.py
"""
import html
import io
import json
import os
import re
import tempfile
import time
import zipfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)

st.set_page_config(page_title="PromoScout", page_icon="🎬", layout="centered")

# API keys: Streamlit Cloud secrets -> env
for k in ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
    try:
        if k in st.secrets:
            os.environ.setdefault(k, st.secrets[k])
    except Exception:  # no secrets file locally -> rely on .env
        break

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea {font-family:'Plus Jakarta Sans', sans-serif;}
.stApp {background:
   radial-gradient(900px 500px at 85% -10%, rgba(255,106,61,0.22), transparent 60%),
   radial-gradient(700px 500px at -10% 10%, rgba(236,72,153,0.16), transparent 60%),
   #0B0B10;}
header[data-testid="stHeader"] {background:transparent;}
[data-testid="stToolbar"], [data-testid="stDecoration"] {display:none;}
section[data-testid="stSidebar"] {background:#111118; border-right:1px solid rgba(255,255,255,0.06);}
.block-container {padding-top:1.6rem; max-width:900px;}
.grad {background:linear-gradient(90deg,#FFB547,#FF6A3D 45%,#EC4899); -webkit-background-clip:text;
       background-clip:text; color:transparent;}
.muted {color:#9CA3AF; font-size:0.9rem;}

/* nav */
.nav {display:flex; justify-content:space-between; align-items:center; margin-bottom:46px;}
.brand {display:flex; align-items:center; gap:10px; font-weight:800; font-size:1.1rem; color:#fff;}
.logo {width:34px; height:34px; border-radius:10px; display:inline-flex; align-items:center; justify-content:center;
       background:linear-gradient(135deg,#FFB547,#FF6A3D 50%,#EC4899); font-size:1.05rem;}
.for {font-size:0.8rem; color:#D1D5DB; border:1px solid rgba(255,255,255,0.14); padding:6px 12px; border-radius:999px;
      background:rgba(255,255,255,0.04);}

/* hero */
.hero {text-align:center; margin-bottom:40px;}
.badge {display:inline-block; font-size:0.8rem; font-weight:600; color:#FFB58F; padding:6px 14px; border-radius:999px;
        background:rgba(255,106,61,0.12); border:1px solid rgba(255,106,61,0.35); margin-bottom:20px;}
.hero h1 {font-size:3.1rem; line-height:1.1; font-weight:800; color:#fff; margin:0 0 16px 0; padding:0; letter-spacing:-0.02em;}
.hero p {font-size:1.12rem; color:#B6B8C3; max-width:620px; margin:0 auto; line-height:1.6;}

/* features */
.features {display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:34px 0 44px 0;}
.feat {background:rgba(255,255,255,0.035); border:1px solid rgba(255,255,255,0.08); border-radius:18px; padding:20px;}
.feat .ic {font-size:1.5rem; margin-bottom:10px;}
.feat b {display:block; color:#fff; font-size:1rem; margin-bottom:4px;}
.feat span {color:#9CA3AF; font-size:0.88rem; line-height:1.5;}

/* section titles */
.sec {font-size:1.5rem; font-weight:800; color:#fff; margin:8px 0 4px 0;}
.secsub {color:#9CA3AF; margin-bottom:18px;}

/* steps */
.step {display:flex; align-items:center; gap:12px; font-weight:700; font-size:1.05rem; margin:22px 0 10px 0; color:#fff;}
.step .num {width:30px; height:30px; border-radius:10px; display:inline-flex; align-items:center; justify-content:center;
            color:#fff; font-size:0.9rem; background:linear-gradient(135deg,#FF6A3D,#EC4899);}
.cost {background:rgba(168,85,247,0.12); border:1px solid rgba(168,85,247,0.3); color:#DDD6FE;
       border-radius:12px; padding:11px 14px; font-size:0.93rem;}
[data-testid="stFileUploaderDropzone"] {background:rgba(255,255,255,0.03); border:1.5px dashed rgba(255,106,61,0.45);
       border-radius:16px;}

/* results tiles */
.tiles {display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin:8px 0 20px 0;}
.tile {border-radius:18px; padding:18px; text-align:center; background:rgba(255,255,255,0.04);
       border:1px solid rgba(255,255,255,0.08);}
.tile b {display:block; font-size:2.1rem; line-height:1.1; font-weight:800;}
.tile span {font-size:0.85rem; color:#9CA3AF;}
.t1 b {color:#FFB547;} .t2 b {color:#FF6A3D;} .t3 b {color:#4ADE80;}

/* promo cards */
[class*="st-key-card_"] {background:linear-gradient(180deg,#17171F,#121218); border-radius:18px;
     padding:20px 22px 10px 22px; border:1px solid rgba(255,255,255,0.07); border-left:5px solid #4B5563;
     box-shadow:0 10px 30px rgba(0,0,0,0.35); margin-bottom:16px;}
[class*="st-key-card_post"] {border-left-color:#22C55E;}
[class*="st-key-card_maybe"] {border-left-color:#F59E0B;}
[class*="st-key-card_reject"] {border-left-color:#EF4444;}
.chead {display:flex; justify-content:space-between; align-items:center; gap:12px;}
.rank {width:40px; height:40px; border-radius:12px; color:#fff; font-weight:800; font-size:1.1rem; flex-shrink:0;
       display:inline-flex; align-items:center; justify-content:center; background:linear-gradient(135deg,#FF6A3D,#EC4899);}
.ctitle {display:flex; align-items:center; gap:12px; font-size:1.15rem; font-weight:700; color:#fff;}
.pill {display:inline-block; padding:4px 12px; border-radius:999px; font-size:0.78rem; font-weight:700;}
.pill-post {background:rgba(34,197,94,0.15); color:#4ADE80;}
.pill-maybe {background:rgba(245,158,11,0.15); color:#FBBF24;}
.pill-skip {background:rgba(239,68,68,0.15); color:#F87171;}
.meta {color:#9CA3AF; font-size:0.82rem; text-align:right; margin-top:5px;}
.label {font-size:0.72rem; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin:16px 0 7px 0;}
.chip {display:inline-block; background:rgba(99,102,241,0.15); color:#C7D2FE; border-radius:10px; padding:5px 11px;
       margin:0 6px 6px 0; font-family:ui-monospace, Menlo, monospace; font-size:0.86rem;}
.duo {display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:12px;}
.box {border-radius:12px; padding:12px 14px; font-size:0.94rem; color:#E5E7EB; line-height:1.5;}
.box .label {margin-top:0;}
.open {background:rgba(255,106,61,0.10);} .open .label {color:#FF9B73;}
.end {background:rgba(168,85,247,0.12);} .end .label {color:#C4A1FF;}
.why {background:rgba(45,212,191,0.08); border-radius:12px; padding:12px 14px; margin-top:10px; font-size:0.94rem;
      color:#E5E7EB; line-height:1.5;}
.why .label {color:#5EEAD4; margin-top:0;}
.bars {display:grid; grid-template-columns:repeat(3,1fr); gap:14px; margin:16px 0 8px 0;}
.bar small {display:flex; justify-content:space-between; color:#9CA3AF; font-size:0.8rem;}
.bar small b {color:#fff;}
.track {height:7px; background:rgba(255,255,255,0.08); border-radius:999px; overflow:hidden; margin-top:5px;}
.fill {height:100%; border-radius:999px;}
.f1 {background:linear-gradient(90deg,#FFB547,#FF6A3D);}
.f2 {background:linear-gradient(90deg,#C084FC,#EC4899);}
.f3 {background:linear-gradient(90deg,#5EEAD4,#22C55E);}
.warn {color:#FCA5A5; font-size:0.85rem;}

/* widgets */
.stButton button[kind="primary"] {background:linear-gradient(120deg,#FF6A3D,#EC4899); border:none; font-weight:700;
       padding:0.7rem 1rem; border-radius:14px; box-shadow:0 8px 24px rgba(255,106,61,0.35);}
.stButton button[kind="primary"]:hover {filter:brightness(1.08);}
.stTabs [aria-selected="true"] {color:#FF8A5B !important;}
.stTabs [data-baseweb="tab-highlight"] {background:#FF6A3D !important;}
.foot {text-align:center; color:#6B7280; font-size:0.82rem; margin:50px 0 10px 0;}
@media (max-width: 680px) {
  .hero h1 {font-size:2.1rem;} .features, .duo, .bars, .tiles {grid-template-columns:1fr;}
}
</style>
""", unsafe_allow_html=True)

OUTPUTS = Path("outputs")
VERDICT = {"post": ("Post it", "pill-post"), "maybe": ("Maybe", "pill-maybe"), "reject": ("Skip", "pill-skip")}
STEP_TEXT = {
    "load": "Read the episodes",
    "stitch": "Tried joining moments from different episodes",
    "validate": "Checked clip lengths and timing",
    "refine": "Fixed clips that broke the rules",
    "dedupe": "Removed repeated clips",
    "rank": "Ranked the clips",
    "report": "Saved the results",
}


# ---------- helpers ----------
def clock(sec: float) -> str:
    m, s = divmod(max(sec, 0), 60)
    return f"{int(m)}:{s:04.1f}"


@st.cache_data(show_spinner=False)
def read_upload(blobs: tuple) -> dict:
    """Unpack the uploaded files and read the episodes (no AI used)."""
    from promo_finder.parser import load_show
    tmp = Path(tempfile.mkdtemp())
    for name, data in blobs:
        if name.lower().endswith(".zip"):
            zipfile.ZipFile(io.BytesIO(data)).extractall(tmp)
        else:
            (tmp / name).write_bytes(data)
    show = load_show(tmp)
    return {"dir": str(tmp), "episodes": sorted(show)}


def past_runs() -> list[Path]:
    if not OUTPUTS.exists():
        return []
    runs = [p for p in OUTPUTS.iterdir() if (p / "promos.json").exists()]
    return sorted(runs, key=lambda p: p.stat().st_mtime, reverse=True)


def run_label(p: Path) -> str:
    when = time.strftime("%d %b, %H:%M", time.localtime(p.stat().st_mtime))
    name = re.sub(r"_\d{8}_\d{6}$", "", p.name).replace("_", " ")
    return f"{name} · {when}"


def esc(t) -> str:
    return html.escape(str(t or ""))


def bar(name: str, val: int, cls: str) -> str:
    return (f"<div class='bar'><small><span>{name}</span><b>{val}/10</b></small>"
            f"<div class='track'><div class='fill {cls}' style='width:{val * 10}%'></div></div></div>")


def promo_card(p: dict):
    j = p.get("judge") or {}
    verdict = j.get("verdict", "none")
    label, css = VERDICT.get(verdict, ("Not rated", "pill-maybe"))
    score = f" · Score {p['score']:.0f}" if p.get("score") is not None else ""
    cuts = "".join(
        f"<span class='chip'>{'Part ' + str(i) + ' · ' if len(p['segments']) > 1 else ''}"
        f"Ep {s['episode']} · {clock(s['start'])} → {clock(s['end'])}</span>"
        for i, s in enumerate(p["segments"], 1))
    body = f"""
    <div class='chead'>
      <div class='ctitle'><span class='rank'>{p['rank']}</span>{esc(p['title'])}</div>
      <div><span class='pill {css}'>{label}</span><div class='meta'>{p['duration']:.0f} sec{score}</div></div>
    </div>
    <div class='label' style='color:#A5B4FC'>Where to cut</div>{cuts}
    <div class='duo'>
      <div class='box open'><div class='label'>Opens with</div>{esc(p['hook'])}</div>
      <div class='box end'><div class='label'>Ends on</div>{esc(p['cliffhanger'])}</div>
    </div>
    <div class='why'><div class='label'>Why it works</div>{esc(p['why'])}</div>"""
    if j:
        body += ("<div class='bars'>" + bar("Opening", j["hook_score"], "f1")
                 + bar("Ending", j["cliffhanger_score"], "f2")
                 + bar("Easy to follow", j["standalone_score"], "f3") + "</div>")
        if j.get("spoiler_risk", 0) >= 6:
            body += f"<div class='warn'>⚠️ May give away too much of the story ({j['spoiler_risk']}/10)</div>"

    with st.container(key=f"card_{verdict}_{p['rank']}_{p['cid']}"):
        st.markdown(body, unsafe_allow_html=True)
        if j.get("issues"):
            with st.expander("What could be better"):
                for issue in j["issues"]:
                    st.markdown(f"- {issue}")
        if p.get("clip_text"):
            with st.expander("Read the clip script"):
                st.text(p["clip_text"])


def show_results(out: Path):
    promos = json.loads((out / "promos.json").read_text())
    rejected = json.loads((out / "rejected.json").read_text()) if (out / "rejected.json").exists() else []
    meta = json.loads((out / "run_meta.json").read_text()) if (out / "run_meta.json").exists() else {}
    top = [p for p in promos if p.get("post_first")]
    others = [p for p in promos if not p.get("post_first")]

    st.markdown("<div class='sec'>✨ Your promos</div><div class='secsub'>Ranked best first, ready to hand to the editor.</div>", unsafe_allow_html=True)
    st.markdown(f"""<div class='tiles'>
      <div class='tile t1'><b>{meta.get("counts", {}).get("episodes", "—")}</b><span>Episodes read</span></div>
      <div class='tile t2'><b>{len(promos)}</b><span>Promos found</span></div>
      <div class='tile t3'><b>{len(top)}</b><span>Post these first</span></div>
    </div>""", unsafe_allow_html=True)

    tabs = st.tabs(["⭐ Post first", f"Other promos ({len(others)})", f"Skipped ({len(rejected)})", "Download"])
    with tabs[0]:
        if not top:
            st.info("No clip was strong enough to recommend. Check the other tabs.")
        st.caption("Ranked best first. Each one starts with something that grabs attention "
                   "and stops on a moment that leaves people wanting more.")
        for p in top:
            promo_card(p)
    with tabs[1]:
        if not others:
            st.caption("Nothing here.")
        for p in others:
            promo_card(p)
    with tabs[2]:
        st.caption("Clips the tool found but dropped, and why.")
        if not rejected:
            st.caption("Nothing was skipped.")
        for r in rejected:
            reason = r.get("reject_reason") or ""
            if r.get("errors"):
                reason += " — " + "; ".join(r["errors"])
            st.markdown(f"- **{r.get('title') or r.get('cid')}**: {reason}")
    with tabs[3]:
        st.caption("Spreadsheet of all promos, a sheet for an editor to mark yes/no, or everything at once.")
        if (out / "promos.csv").exists():
            st.download_button("Promos spreadsheet (.csv)", (out / "promos.csv").read_bytes(),
                               file_name="promos.csv", use_container_width=True)
        if (out / "review_sheet.csv").exists():
            st.download_button("Editor review sheet (.csv)", (out / "review_sheet.csv").read_bytes(),
                               file_name="review_sheet.csv", use_container_width=True)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for f in out.iterdir():
                z.write(f, f.name)
        st.download_button("Everything (.zip)", buf.getvalue(), file_name=f"{out.name}.zip",
                           use_container_width=True)


# ---------- page ----------
st.markdown("""
<div class='nav'>
  <div class='brand'><span class='logo'>🎬</span>PromoScout</div>
  <div class='for'>Made for Kuku FM</div>
</div>
<div class='hero'>
  <div class='badge'>✨ Promos for microdramas, in minutes</div>
  <h1>Turn every episode into<br><span class='grad'>scroll-stopping promos</span></h1>
  <p>Upload a show's scripts. We find the best 20–60 second moments to post on Instagram,
  YouTube and TikTok — and tell you exactly where to cut.</p>
</div>
<div class='features'>
  <div class='feat'><div class='ic'>⚡</div><b>Grabs attention fast</b>
    <span>Every clip opens with a slap, a reveal or a shocking line in the first 3 seconds.</span></div>
  <div class='feat'><div class='ic'>🎯</div><b>Leaves them hooked</b>
    <span>Clips stop on an unanswered moment, so viewers need to know what happens next.</span></div>
  <div class='feat'><div class='ic'>🏆</div><b>Ranked and ready</b>
    <span>See which promos to post first, why they work, and where each one could be better.</span></div>
</div>
<div class='sec'>Find your promos</div>
<div class='secsub'>Three quick steps. No editing needed.</div>
""", unsafe_allow_html=True)


def step(n: int, text: str):
    st.markdown(f"<div class='step'><span class='num n{n}'>{n}</span>{text}</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("Past results")
    runs = past_runs()
    if runs:
        pick = st.selectbox("Open a previous run", runs, format_func=run_label, index=None,
                            placeholder="Choose one…")
        st.caption("Opening past results is free — it uses no AI requests.")
        if pick:
            st.session_state["out_dir"] = str(pick)
    else:
        st.caption("Nothing yet.")

# Step 1
step(1, "Upload the episodes")
files = st.file_uploader("A .zip of episode scripts, or several .txt files", type=["zip", "txt"],
                         accept_multiple_files=True, label_visibility="collapsed")

if files:
    info = read_upload(tuple((f.name, f.getvalue()) for f in files))
    eps = info["episodes"]
    if not eps:
        st.error("No episode scripts found in that upload. Please upload the screenplay .txt files "
                 "(or a .zip of them) — videos can't be read.")
        st.stop()
    st.success(f"Found {len(eps)} episodes.")

    # Step 2
    step(2, "Choose episodes")
    if len(eps) > 1:
        lo, hi = st.select_slider("Episodes", options=eps, value=(eps[0], eps[min(2, len(eps) - 1)]),
                                  label_visibility="collapsed")
    else:
        lo = hi = eps[0]
    chosen = [e for e in eps if lo <= e <= hi]
    st.caption(f"Episodes {lo}–{hi} selected ({len(chosen)}). Start small to save AI requests.")

    with st.expander("More options"):
        model = st.text_input("AI model", os.getenv("MODEL", "groq:openai/gpt-oss-120b"))
        mix = st.checkbox("Also mix moments from different episodes", value=len(chosen) > 1)
        rate_n = st.slider("How many clips to rate", 3, 30, int(os.getenv("MAX_JUDGED", 5)))

    per_ep = int(os.getenv("PROMOS_PER_EPISODE", 2))
    found = len(chosen) * per_ep + (3 if mix else 0)
    calls = len(chosen) + (1 if mix else 0) + min(rate_n, found)
    st.markdown(f"<div class='cost'>💡 This will use about <b>{calls} AI requests</b> "
                f"(1 per episode + 1 per clip rated).</div>", unsafe_allow_html=True)

    # Step 3
    step(3, "Find promos")
    if st.button("Find promos", type="primary", use_container_width=True):
        os.environ.update(MODEL=model, MODEL_FINDER=model, MODEL_JUDGE=model,
                          STITCHED_PROMOS="3" if mix else "0", MAX_JUDGED=str(rate_n))
        import importlib
        import promo_finder.config as cfg
        importlib.reload(cfg)
        from promo_finder import llm, nodes, graph, rank
        for m in (llm, nodes, rank, graph):
            importlib.reload(m)
        from promo_finder.parser import load_show

        show = {n: e for n, e in load_show(info["dir"]).items() if n in chosen}
        total = len(chosen) + min(rate_n, found) + 6
        done = {"n": 0, "find": 0, "judge": 0}
        progress = st.progress(0.0, text="Starting…")

        def on_update(node, upd):
            done["n"] += 1
            if node == "find_in_episode":
                done["find"] += 1
                text = f"Looked through episode {done['find']} of {len(chosen)}"
            elif node == "judge_one":
                done["judge"] += 1
                text = f"Rated clip {done['judge']}"
            else:
                text = STEP_TEXT.get(node, "Working…")
            progress.progress(min(done["n"] / total, 0.99), text=text)

        stem = re.sub(r"[^A-Za-z0-9]+", "_", Path(files[0].name).stem)[:30].strip("_") or "show"
        out_dir = OUTPUTS / f"{stem}_ep{lo}-{hi}_{time.strftime('%Y%m%d_%H%M%S')}"
        t0 = time.time()
        try:
            final = graph.run(info["dir"], str(out_dir), show=show, on_update=on_update)
        except Exception as e:  # keep the message readable
            progress.empty()
            st.error(f"Something went wrong: {e}")
            st.stop()
        progress.progress(1.0, text=f"Done in {time.time() - t0:.0f} seconds")
        st.session_state["out_dir"] = final["out_dir"]

if out := st.session_state.get("out_dir"):
    st.divider()
    show_results(Path(out))

st.markdown("<div class='foot'>PromoScout · built for Kuku FM microdramas</div>", unsafe_allow_html=True)
