# PromoScout — Full Project Handoff (for writing the submission documents)

> **To the Claude reading this:** this file describes everything built, run, tested and fixed for
> Kuku FM's AI Generalist assignment, **Problem 1: Find the Promos**. Use it to write the submission
> documents (the ≤2-page solution doc following `SOLUTION_DOC_TEMPLATE.md`, a polished README, and any
> summary the candidate asks for). **Only use the numbers and facts written here.** Where something was
> *not* done (e.g. a hand-labelled gold-set evaluation, a full 50-episode real run), say so honestly or
> leave a clearly marked placeholder. Don't present it as done. Write in plain, simple English, with no
> unnecessary jargon (the candidate asked for this).

---

## 1. The assignment (Kuku FM — Problem 1)

Kuku FM releases new microdrama shows every week. Today an editor watches every episode and hand-picks
promo moments. The task: **build a tool that reads a microdrama screenplay and finds the best promos.**

- **Promo** = a 20–60 second clip taken from the show itself, posted on Instagram / TikTok / YouTube to
  pull in new viewers. Usually one continuous stretch; may join a few moments from one or several episodes.
- **A good promo:** (1) opens on a **hook** within the first 3 seconds (slap, reveal, shocking line);
  (2) ends on a **cliffhanger** (cuts at an unresolved moment); (3) **makes sense on its own** to someone
  who has never seen the show.
- **Scope:** only find the moments and the start/end points. No editing, music or text overlays.
- **Required output:** for each promo, the episode and start/end timestamps of every segment (in order),
  the hook, the cliffhanger, one line on why it works. **Rank them**: which to post first and why.
- **Check quality:** where does the tool pick badly?

---

## 2. Input data

- Kuku's input pack: a zip of **50 episode screenplays** for the show
  **"I Married a Broken Soldier. He was a Duke"** (files `episode-001-…txt` … `episode-050-…txt`, ~529 KB).
  It is confidential and kept out of git (`data/` is git-ignored).
- Format, one block per beat:
  ```
  EPISODE NUMBER: Episode 1
  EPISODE LOGLINE: …
  CONTINUITY NOTES: …
  SCENE 1
  Scene heading: INT. CHAPEL - DAY
  **LADY JULIANA (Confused, Breathless):**
  Start: (00:13.50) | End: (00:14.30)
  "Why?"
  ```
  Labels are character names (dialogue) or `CAMERA`, `ACTION`, `SOUND FX`/`SFX`.
- Parsed result for the whole show: **50 episodes, ~3,700 timestamped beats**. Episodes run ~1:10 to
  ~3:20 each. Roughly half of all beats are CAMERA lines (e.g. Ep 1: 95 beats = 37 dialogue, 7 action,
  50 camera, 1 sfx).
- Main characters seen in outputs: Lady Juliana (the jilted bride), Gerald (the "former groom"),
  the Lady in Gold Gown / Clarissa (Juliana's sister), the Noble Matriarch, a Bearded Stranger (the
  "broken soldier", who turns out to be a Duke).
- An `.mp4` video was uploaded by mistake once. The tool reads **text screenplays only**, not video.
  The UI now shows a clear message when no scripts are found.

---

## 3. What we built: PromoScout

**Stack:** Python 3.12, **LangChain** (model-agnostic structured output via `init_chat_model`),
**LangGraph** (parallel fan-out, validate→refine loop, AI judge), **Pydantic** schemas,
**Streamlit** web app. Model in use: **`openai/gpt-oss-120b` on Groq** (free tier).

### 3.1 Pipeline (LangGraph)

```
START → load (code) → find_in_episode × N (AI, one call per episode, in parallel)
      → stitch (AI, one call: joins moments across episodes)
      → validate (code) ──rule errors & rounds left──→ refine (AI) ──→ validate
                        └─all ok / out of rounds──────→ dedupe (code)
      → judge_one × M (AI, one call per promo, sees ONLY the clip) → rank (code) → report (code) → END
```

| Step | AI or code | What it does / why |
|---|---|---|
| **load / parse** | Code | Turns screenplay text into timestamped "beats" with IDs like `E07-B023`. Deterministic, so **timestamps are never invented**. |
| **Show context** | Code | Uses existing episode loglines + continuity notes (premise + previous 3 episodes) instead of paying for a summary call. |
| **find_in_episode** | AI | Reads one episode's beats and proposes the best promos. The AI returns **beat IDs only**, never times. Camera lines are left out to save tokens (`INCLUDE_CAMERA=0`); actions carry the visuals. |
| **stitch** | AI | Takes the strongest single-episode candidates and builds promos that join 2–3 segments from **different episodes** (e.g. open on a later explosive moment, cut to the setup). |
| **validate (+ auto-repair)** | Code | Hard rules checked in code: total 20–60 s; hook starts ≤3 s into the clip; clip ends ≤3 s after the cliffhanger beat; ≤3 segments; each segment ≥3 s; no overlapping segments; beat IDs must exist. Simple cases are **auto-fixed for free** (start the clip on the hook, cut right on the cliffhanger, fix reversed ranges / wrong episode numbers). |
| **refine** | AI (≤ N rounds) | Promos that still break rules go back to the AI with the exact error ("too long: 74 s – trim it"). Off in our low-cost settings (`MAX_REFINE_ROUNDS=0`). |
| **dedupe** | Code | Drops near-duplicate clips (time overlap IoU ≥ 0.5), keeps the higher self-scored one; caps how many get judged (`MAX_JUDGED`). |
| **judge_one** | AI | A strict reviewer that sees **only the clip transcript**, like a stranger scrolling. Scores hook, cliffhanger, standalone (0–10), spoiler risk (0–10), verdict post / maybe / reject, and lists concrete issues. |
| **rank** | Code | Transparent formula (below), plus posting-order rules. |
| **report** | Code | Writes all output files (below). |
| **Final approval** | **Human** | Editor fills `review_sheet.csv`; those labels can become evaluation data. |

### 3.2 Ranking formula (code, tunable in `promo_finder/config.py`)

```
score = 10 × (0.35·hook + 0.30·cliffhanger + 0.25·standalone + 0.10·(10 − spoiler_risk))
      + early-episode bonus (up to +5 points; earlier episodes land new viewers at the story's start)
      − 30 if the judge said "reject"
```
**"Post these first" list (top 10):** best score first, but **max 2 promos per episode** and **never
the same hook twice**, so the first posts are varied. Each promo gets a plain-English "why this rank"
line (e.g. "hook 7/10, cliffhanger 8/10, standalone 7/10; from ep 1, early episode…").

### 3.3 Key design decisions

1. **The AI never writes timestamps.** It picks beat IDs, and code looks up real times. This removes
   timestamp hallucination completely.
2. **Rules in code, taste in AI.** Anything checkable (length, 3-second hook window, cut point, overlap)
   is checked deterministically and for free. The AI only does what needs a sense of drama.
3. **The judge is blind to the show.** It only sees the clip, which directly tests "makes sense on its own".
4. **Model-agnostic.** Any `provider:model` LangChain supports can be swapped in with one line
   (`MODEL=` in `.env`, or `--model` on the CLI); finder and judge can be different models.
5. **Free-tier friendly.** Rate limiter, retries on HTTP 429, a disk cache (`.cache/`) so a crashed or
   re-run job doesn't pay twice, and one failed episode never kills the whole run.
6. **Human in the loop.** The editor review sheet closes the loop and becomes future evaluation data.

### 3.4 Outputs per run (`outputs/<run>/`)

| File | Contents |
|---|---|
| `report.md` | Readable ranked list: "Post these first", other promos, rejected promos with reasons |
| `promos.csv` / `promos.json` | Rank, score, segments (`Ep3 01:24.00-02:20.30 + …`), duration, hook, cliffhanger, why it works, why this rank, judge scores, verdict, issues, clip script |
| `candidates_raw.json` | Every unedited AI proposal |
| `rejected.json` | Promos that failed rules or were duplicates, with reasons |
| `review_sheet.csv` | For the editor: post y/n, better start, better end, notes |
| `run_meta.json` | Models, counts, first-pass rule pass rate, runtime, token usage |

### 3.5 How to run

```bash
python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY (or GOOGLE_API_KEY), set MODEL=groq:openai/gpt-oss-120b
python tests/test_offline.py data/show.zip              # free plumbing test, no API key
python run.py data/show.zip --episodes 1-3              # small real run
python run.py data/show.zip                             # full show
streamlit run app.py                                    # web app
python eval/evaluate.py outputs/<run>/promos.json eval/gold.json [--review outputs/<run>/review_sheet.csv]
```

### 3.6 Settings used (to keep API usage low on Groq's free tier)

```
MODEL=groq:openai/gpt-oss-120b
REQUESTS_PER_SECOND=0.1     MAX_CONCURRENCY=1
PROMOS_PER_EPISODE=2        MAX_JUDGED=5
MAX_REFINE_ROUNDS=0         STITCHED_PROMOS=0   (web app: "mix episodes" option turns this on, 3 promos)
```
Recommended for a final full-show run: `STITCHED_PROMOS=3`, `MAX_JUDGED=15` (adds only ~11 calls).

---

## 4. The web app (PromoScout UI)

Built in Streamlit and redesigned during this project to be **simple, plain-language and premium**,
and branded **"PromoScout — Made for Kuku FM"** (Kuku's real logo is not used).

- **Landing page:** dark theme, warm amber→orange→pink gradient, Plus Jakarta Sans font. Headline
  "Turn every episode into *scroll-stopping promos*". Three feature cards: ⚡ Grabs attention fast,
  🎯 Leaves them hooked, 🏆 Ranked and ready.
- **Three steps:** (1) Upload the episodes (.zip or .txt). The app instantly says "Found 50 episodes"
  without using AI. (2) Choose an episode range with a slider; a box shows **"This will use about N AI
  requests"** before you run. (3) Find promos, with a plain-language progress bar ("Looked through
  episode 2 of 3", "Rated clip 4").
- **More options** (tucked away): AI model, "Also mix moments from different episodes", how many clips to rate.
- **Results:** summary tiles (episodes read / promos found / post these first) and tabs
  **Post first · Other promos · Skipped · Download**. Each promo is a card with: rank badge, title,
  **Post it / Maybe / Skip** label (coloured card edge: green/amber/red), length and score,
  **Where to cut** chips (`Ep 3 · 1:24.0 → 2:20.3`), **Opens with**, **Ends on**, **Why it works**,
  colour bars for Opening / Ending / Easy to follow (out of 10), a spoiler warning if high, and
  expandable "What could be better" and "Read the clip script".
- **Past results** in the sidebar reopen earlier runs for free (no AI calls).
- **Downloads:** promos spreadsheet (.csv), editor review sheet (.csv), everything (.zip).

### Deployment
- GitHub repo: `deepakp-tech/PromoScout` (branch `main`). The API key (`.env`), Kuku's scripts
  (`data/`) and run results (`outputs/`, which contain script lines) are git-ignored.
- Deployed on **Streamlit Community Cloud** (`app.py`, Python 3.12); the Groq key and low-usage
  settings go in the app's Secrets.

---

## 5. How we tested and validated it

### 5.1 Parser check (no AI)
- All **50 episodes** of the real pack parsed; per-episode durations and beat counts printed and
  sanity-checked (e.g. Ep 1 = 2:18, 95 beats; Ep 36 = 3:20, 121 beats; Ep 50 = 1:20, 40 beats).

### 5.2 Offline end-to-end test with a fake AI (`tests/test_offline.py`, no API key, no cost)
- Replaces the model with a deterministic fake that picks a hook-like line ("!") and a later line,
  and checks the **plumbing**: parsing, parallel fan-out, validation, auto-repair, refine loop, dedupe,
  ranking and every output file.
- On the full 50-episode pack: **passed**: 150 candidates, 70% passed the rules on the first try,
  too-short/duplicate clips correctly rejected with reasons, all output files written.
- Also run on a small made-up 3-episode sample show (written in the same format, used only to test
  the app before the real pack arrived): passed; it correctly rejected clips under 20 s.

### 5.3 Real AI runs on Groq

**Run A — real Kuku pack, episodes 1–3 (CLI), `outputs/ep1-3_test/`**
- Model `groq:openai/gpt-oss-120b` for both finder and judge. Runtime **141 s**,
  **23,065 tokens** (15,075 in / 7,990 out, incl. 6,040 reasoning).
- 6 candidates → **100% passed the rules on the first try** → 1 duplicate removed → **5 ranked**, 0 failures.

| # | Promo | Segments | Length | Score | Judge (hook/cliff/standalone/spoiler) | Verdict |
|---|---|---|---|---|---|---|
| 1 | Cold Change, Burning Resolve | Ep1 01:00.10–01:12.10 + Ep1 02:08.50–02:17.50 | 21.0 s | 79.0 | 7/8/7/2 | post |
| 2 | Blade to Ring | Ep3 01:24.00–02:20.30 | 56.3 s | 75.0 | 8/8/6/2 | post |
| 3 | Betrayal Question | Ep2 00:00.00–00:27.40 | 27.4 s | 71.0 | 7/7/6/2 | maybe |
| 4 | Betrayal at the Altar | Ep1 00:15.50–00:50.00 | 34.5 s | 66.5 | 4/8/7/4 | maybe |
| 5 | Defiant Ultimatum | Ep2 01:14.40–01:47.40 | 33.0 s | 52.0 | 4/3/7/1 | maybe |

Examples of the output wording:
- #1 hook: groom coldly says *"I changed my mind."*; cliffhanger: tense strings as Juliana clenches her
  fist. Why: "shocking betrayal line; cut to clenched fist leaves the conflict unresolved."
- #2 hook: the Bearded Stranger punches a guard to the floor; cliffhanger: he kneels with a ring,
  *"Lady Juliana… accept my hand."* Why: violent rescue → proposal, leaves viewers craving her answer.
- #3 hook: *"I cannot marry you, Juliana."*; cliffhanger: *"A better choice? Is that what she is?"*

**Run B — made-up sample show, episodes 1–3 (web app)**: 61.9 s, 12,882 tokens; 6 candidates,
100% first-pass rule pass, 3 duplicates removed, 3 ranked (top: "Slap to Freeze", score 84,
judge 9/8/7). Used to test the web app end to end, not for quality claims.

**Run C — a 3-episode test upload through the web app**: 109.1 s, 20,231 tokens; 6 candidates,
**83% first-pass rule pass**; 1 rejected for being **too short (18.0 s, min 20 s)** (refine was off,
so code rejected it rather than send it back to the AI); 5 ranked. The judge gave one promo a
**reject** verdict (score 34.5, "Heir Reveal & Dark Secret"); it was correctly kept out of the
"post first" list.

### 5.4 What the AI judge flagged (evidence for "where does the tool pick badly")
Taken from the real Kuku run's judge issues:
- **Weak verbal hooks.** Several clips open on dialogue with no visual shock in the first 3 seconds
  (e.g. "Gerald is waiting for me" scored hook 4/10; "Dignity?" scored hook 4/10).
- **Cliffhangers that resolve or just declare.** "Defiant Ultimatum" ends on a statement, not an
  open question (cliffhanger 3/10).
- **Needs backstory.** Labels like "THE FORMER GROOM" or a sudden new name (Clarissa) confuse a
  stranger; standalone scores for top clips were only 6–7/10.
- **Pacing.** A 56 s clip near the upper limit was flagged as possibly too slow for TikTok/Reels.

### 5.5 Engineering problems found and fixed during testing
| Problem | How it showed up | Fix |
|---|---|---|
| Model retired | `llama-3.3-70b-versatile` returned HTTP 404 "model not found" | Listed the models the key can use via Groq's API; switched to `openai/gpt-oss-120b` |
| Free-tier rate limits | HTTP 429 "Too Many Requests" during runs | Built-in retry/back-off handled it; every call eventually succeeded; throttled to 0.1 req/s, 1 at a time |
| Wrong file type | Uploading an `.mp4` → "No episodes found" crash | UI now reads uploads first (no AI) and shows a plain message that only screenplay text works |
| UI ignored the low-cost settings | Stitch checkbox and request rate were hard-coded on | UI defaults now come from `.env` |
| Crash after a run on Streamlit Cloud | `TypeError` drawing rating bars | The progress-bar variable was named `bar` and overwrote the `bar()` helper; renamed it to `progress` |
| UI style issues | Seen in headless-browser screenshots | Hid Streamlit's "Deploy" toolbar overlapping the header; brightened a label that was unreadable on dark |

### 5.6 UI testing
- Streamlit `AppTest` smoke tests: page loads with no exceptions; past results render 5 promo cards,
  5 rating-bar rows, 10 expanders, 4 tabs.
- Headless Chrome (Playwright) screenshots of the landing page and results were checked visually.

### 5.7 Quality-evaluation tooling built (ready, but **not yet run with real labels**)
- `eval/evaluate.py` compares a run with hand-picked "gold" promos: **recall** (gold promos found,
  match = time overlap IoU ≥ 0.3), **precision@10**, and editor approval rate from a filled review sheet.
- `eval/gold.example.json` has 2 *example* entries only (Ep 1 altar confrontation; Ep 1 "the daughter
  people tolerate"). **A real gold set (10–15 promos over 5–6 episodes) has not been labelled yet**, so
  there are no recall/precision numbers. Mark these as "to be filled" in the solution doc.
- The **first-pass rule pass rate** (100% / 100% / 83% across the 3 real runs) is tracked automatically.

---

## 6. Cost and scale

- Measured: **~4–8k tokens per episode** including judging (Run A: 23k tokens for 3 episodes, 141 s,
  under heavy rate-limiting). Free on Groq's free tier.
- Calls per run ≈ 1 per episode + 1 stitch + 1 per judged promo (+ refine calls if on).
  A full 50-episode show with the recommended settings ≈ **~65 calls, ~300–400k tokens**. This may hit
  Groq's free daily token limit; the disk cache lets the run resume the next day without paying twice.
- With a paid flash-class model this is well under $1 per show. Editor time drops from watching
  ~100 minutes of episodes to reviewing ~10 ranked clips.
- **Not done yet:** a real full 50-episode run (only the free offline test covered all 50).

---

## 7. Assumptions (the brief was silent)
- Script timestamps ≈ final edit timestamps (an editor may nudge cuts by ±1 s).
- "Hook in the first 3 s" = hook beat starts ≤3 s after clip start; "ends on cliffhanger" = cut ≤3 s
  after that beat.
- Earlier episodes get a small ranking bonus because promos send new viewers to the start of the story.
- Max 3 segments per promo; stitched promos may run out of story order (flash-forward hook).
- Text is all the tool sees, so visual-only moments are only as good as their ACTION/CAMERA lines.

## 8. Known limitations / where it picks badly
1. **Visual hooks are under-weighted.** The finder skips CAMERA lines (to save tokens), so a slap that
   only exists in camera directions can be missed. The judge does see camera lines.
2. **Same character, many names** (LADY JULIANA / JULIANA; LADY IN GOLD GOWN / CLARISSA; THE FORMER
   GROOM / GERALD) can confuse both the AI and a stranger.
3. **Self-grading bias:** finder and judge were the same model in all runs; a different judge model
   would be fairer.
4. **Standalone is the weakest score** (top clips 6–7/10). Many dramatic moments need backstory.
5. **Low-cost settings trade quality:** refine off means fixable clips (e.g. 18 s) are dropped;
   judging only 5 means the rest aren't ranked; stitched promos weren't produced in the real runs.
6. **No audio/video:** can't see actual cut points, music stings or loudness peaks.
7. Small: in web-app runs, `run_meta.json` stores a temp folder name as the show name.

## 9. What I'd do next
- Label a 10–15 promo gold set and report recall / precision@10; compare judge vs human on 10 clips.
- Use a different (stronger) model as the judge; turn refine and stitching on for the final run.
- Add video/audio signals (scene cuts, loudness peaks) to snap cut points; a per-show "don't spoil" list.
- Learn ranking weights from editor approvals and real promo performance (click-through, watch time).
- Merge character aliases automatically before sending to the AI.

## 10. AI tools used (for the "AI tools" section)
- **Claude (Claude Code)** helped run, debug, redesign and deploy the project in this session: set up
  the environment, diagnosed the retired Groq model and switched models, fixed the UI settings bug and
  the post-run crash, redesigned the Streamlit UI, and wrote this handoff.
- **Where the AI got it wrong (honest examples):** (1) it first configured `llama-3.3-70b-versatile`,
  which Groq had retired, so the first real run failed with 404s; (2) it introduced the `bar` naming
  bug in the UI redesign that crashed the deployed app after a run, which its own smoke tests missed
  because they only opened past results.
- **Groq `openai/gpt-oss-120b`** is the model inside the tool (finder + judge).

## 11. File map
```
promo_finder/  parser.py (screenplay → beats)   schemas.py (AI output shapes)   prompts.py
               llm.py (model, rate limit, retry, cache)   timing.py (rules, auto-repair, overlap)
               nodes.py (pipeline steps)   graph.py (LangGraph wiring)   rank.py   report.py   config.py
app.py (PromoScout web app)   .streamlit/config.toml (dark theme)   run.py (CLI)
tests/test_offline.py   eval/evaluate.py   eval/gold.example.json   SOLUTION_DOC_TEMPLATE.md
```
