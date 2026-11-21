# PromoScout — Kuku Promo Finder (Problem 1: Find the Promos)

Reads a microdrama screenplay (all episodes) and returns **ranked 20-60 s promo clips**: each
with episode and start/end timestamps for every segment, the hook, the cliffhanger, one line on why it
works, a reason for its rank, and where the tool thinks it is weak.

Built with **LangChain** (model-agnostic structured output) and **LangGraph** (parallel fan-out,
validate → refine loop, LLM-as-judge).

---

## 1. Quick start

```bash
git clone <your-repo> && cd kuku-promo-finder
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # paste a free GOOGLE_API_KEY or GROQ_API_KEY

# put the input pack in data/ (zip or folder) - it is git-ignored
python tests/test_offline.py data/show.zip               # 1. plumbing test, no API key, no cost
python run.py data/show.zip --episodes 1-3               # 2. small real run (~2 min)
python run.py data/show.zip                              # 3. full run -> outputs/<show>_<time>/
streamlit run app.py                                     # 4. UI: upload zip, pick model, download results
```

Swap the model for the whole pipeline, or per step:

```bash
python run.py data/show.zip --model groq:llama-3.3-70b-versatile
python run.py data/show.zip --finder-model google_genai:gemini-2.5-flash --judge-model openai:gpt-4.1
```
Any `provider:model` that LangChain's `init_chat_model` supports works (install that provider's
package). Model names change often, so check the provider's current free models.

---

## 2. How it works

```
START → load (code) ─┬─ find_in_episode ×50 (LLM, parallel via Send) ─┬→ stitch (LLM, cross-episode)
                     └──────────────────────────────────────────────────┘
      → validate (code) ──errors & rounds left──→ refine (LLM) ──→ validate
                        └─all ok / out of rounds─→ dedupe (code)
      → judge_one ×N (LLM, parallel, sees ONLY the clip) → rank (code) → report (code) → END
```

| Step | AI or code | Why |
|---|---|---|
| Parse screenplay → 3,700 timestamped *beats* | Code | Deterministic; timestamps are never invented |
| Show context | Code | Episode loglines + continuity notes already exist, so no summarising call is needed |
| Find hooks / cliffhangers / boundaries | LLM | Needs a sense of drama. The LLM returns **beat IDs only** |
| Duration 20-60 s, hook ≤3 s in, cut ≤3 s after cliffhanger, no overlap | Code | Hard rules, so code checks them. Code also auto-fixes simple cases |
| Fix promos that still break rules | LLM (≤2 rounds) | Gets the exact error message ("too long: 74 s") |
| Judge hook / cliffhanger / standalone / spoiler | LLM | Sees only the clip transcript, like a stranger scrolling |
| Rank + posting order | Code | Transparent weighted formula; max 2 per episode in the top 10; no reused hook |
| Final approval | **Human** | Editor fills `review_sheet.csv`; those labels become eval data |

All knobs (weights, limits, rate limits) are in `promo_finder/config.py` and can be overridden in `.env`.

---

## 3. Outputs (`outputs/<run>/`)

| File | What |
|---|---|
| `report.md` | Readable ranked list: "post these first", then the rest, then rejected promos and why |
| `promos.csv` / `promos.json` | Rank, score, segments (`Ep3 00:41.20-01:12.80 + Ep4 …`), hook, cliffhanger, why, judge scores and issues |
| `candidates_raw.json` | Every unedited LLM proposal |
| `rejected.json` | Promos that failed the rules or were duplicates, with reasons |
| `review_sheet.csv` | For the editor: post y/n, better start/end, notes |
| `run_meta.json` | Models, counts, first-pass rule pass rate, runtime, token usage |

---

## 4. Checking quality

```bash
# 1. Hand-label 10-15 promos across 5-6 episodes -> eval/gold.json (format: eval/gold.example.json)
python eval/evaluate.py outputs/<run>/promos.json eval/gold.json
# 2. After an editor fills review_sheet.csv
python eval/evaluate.py outputs/<run>/promos.json eval/gold.json --review outputs/<run>/review_sheet.csv
```
Reports recall vs your gold promos (time IoU ≥ 0.3), precision@10, editor approval rate, and,
from `run_meta.json`, how often the LLM's first answer already passed the rules.

Known weak spots to look for: visual-only hooks (a slap that is only in CAMERA lines), the same
character appearing under several names (LADY JULIANA / JULIANA, LADY IN GOLD GOWN / CLARISSA),
promos that need backstory, and script timestamps that may drift from the final edit.

---

## 5. Cost and scale (one 50-episode show)

About 54k tokens of screenplay without camera lines. Roughly 50 finder calls, 1 stitch call,
up to about 30 refine calls and up to 60 judge calls make about 140 calls and about 350-400k tokens.
On free tiers the rate limiter keeps it under the limits; a full show takes about 15-25 minutes. The disk
cache (`.cache/`) means a crashed run resumes without paying again. With a flash-class paid model
this costs well under $1 per show. With weekly releases, the work is one batch job per show plus
editor review of the top 10.

---

## 6. Deploy (free)

**Streamlit Community Cloud:** push the repo (without `data/`) → New app → `app.py` → add
`GOOGLE_API_KEY` (or `GROQ_API_KEY`) under *Secrets*. Reviewers upload the zip in the UI.

## 7. Project layout

```
promo_finder/  parser.py  schemas.py  prompts.py  llm.py  timing.py  nodes.py  graph.py  rank.py  report.py  config.py
run.py  app.py  eval/evaluate.py  eval/gold.example.json  tests/test_offline.py
```
