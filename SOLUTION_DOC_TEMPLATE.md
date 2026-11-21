# Solution doc: skeleton (fill in with YOUR numbers and decisions, export to a ≤2-page PDF)

## 1. Problem & why
Problem 1. Why: <your reason, e.g. "editors do this by hand for every weekly show; the output is
easy to check (timestamps); the screenplays are already structured">.

## 2. Assumptions (the brief was silent)
- Script timestamps ≈ final edit timestamps (may drift; an editor nudges cuts by ±1 s).
- "Hook in the first 3 s" = the hook beat starts ≤3 s after the clip start; "ends on cliffhanger" = cut ≤3 s after that beat.
- Promos target new viewers, so earlier episodes get a small ranking bonus (they land viewers at the start).
- Max 3 segments per promo; stitched promos may run out of story order (flash-forward hook).
- Screenplay text is all we see: visual-only moments are only as good as the ACTION lines.

## 3. How it works
<LangGraph diagram + AI / code / human table from README>. Key design choice: the LLM only
returns beat IDs, code turns them into timestamps and enforces the rules → no invented timestamps.

## 4. Scale & cost
<calls, tokens, minutes and $ from run_meta.json> per show; × weekly shows; editor time drops
from watching ~100 min of episodes to reviewing 10 clips.

## 5. Quality: how I know it's good
- Gold set: <n> promos hand-picked from episodes <..>. Recall <x>%, precision@10 <y>%.
- First-pass rule pass rate <z>% → after refine <w>%.
- Judge vs me on 10 promos: agreed on <k>/10.
- Where it fails (real examples from outputs/): 1) … 2) … 3) …

## 6. AI tools used & one place they got it wrong
<e.g. "Claude helped scaffold the graph; it assumed a timestamp format before seeing the files" /
"Gemini returned beat IDs that did not exist in ep 12 - caught by validate">.

## 7. What I'd do next
Use video/audio (scene-cut detection, loudness peaks) to snap boundaries; learn ranking weights
from editor approvals and real promo CTR; a per-show "do not spoil" list.
