"""Deterministic screenplay parser.

Turns Kuku's timestamped screenplay .txt files into a list of `Beat`s.
No LLM here: timestamps must never be invented, so they always come from this file.

Expected block format (one per beat):

    **LADY JULIANA (Confused, Breathless):**
    Start: (00:13.50) | End: (00:14.30)
    "Why?"
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

LABEL_RE = re.compile(r"^\*\*(?P<label>.+?):\*\*\s*$")
TIME_RE = re.compile(
    r"^Start:\s*\((?P<s>[\d:.]+)\)\s*\|\s*End:\s*\((?P<e>[\d:.]+)\)\s*$"
)
SCENE_RE = re.compile(r"^SCENE\s+(\d+)", re.I)
HEADING_RE = re.compile(r"^Scene heading:\s*(.+)$", re.I)
EP_NUM_RE = re.compile(r"^EPISODE NUMBER:\s*Episode\s*(\d+)", re.I)
LOGLINE_RE = re.compile(r"^EPISODE LOGLINE:\s*(.+)$", re.I)
CONT_RE = re.compile(r"^CONTINUITY NOTES:\s*(.+)$", re.I)
FILE_EP_RE = re.compile(r"episode-(\d+)", re.I)

NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx"}


def ts_to_sec(ts: str) -> float:
    """'01:03.40' -> 63.4 ; '1:02:03.5' -> 3723.5"""
    parts = [float(p) for p in ts.split(":")]
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return round(sec, 2)


def sec_to_ts(sec: float) -> str:
    m, s = divmod(max(sec, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


@dataclass
class Beat:
    id: str            # e.g. "E07-B023" (globally unique, used by the LLM instead of times)
    episode: int
    idx: int           # position inside the episode
    scene: int
    kind: str          # dialogue | action | camera | sfx
    speaker: str | None
    tone: str | None
    start: float
    end: float
    text: str

    def render(self) -> str:
        """Compact one-line form sent to the LLM."""
        t = f"{sec_to_ts(self.start)}-{sec_to_ts(self.end)}"
        if self.kind == "dialogue":
            tone = f" ({self.tone})" if self.tone else ""
            return f"[{self.id} {t}] {self.speaker}{tone}: {self.text}"
        return f"[{self.id} {t}] <{self.kind.upper()}> {self.text}"


@dataclass
class Episode:
    number: int
    logline: str = ""
    continuity: str = ""
    beats: list[Beat] = field(default_factory=list)
    scenes: dict[int, str] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return max((b.end for b in self.beats), default=0.0)

    def beat(self, beat_id: str) -> Beat | None:
        return next((b for b in self.beats if b.id == beat_id), None)

    def transcript(self, include_camera: bool = False) -> str:
        lines, cur_scene = [], None
        for b in self.beats:
            if b.scene != cur_scene:
                cur_scene = b.scene
                lines.append(f"-- SCENE {b.scene}: {self.scenes.get(b.scene, '')}")
            if b.kind == "camera" and not include_camera:
                continue
            lines.append(b.render())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["duration"] = self.duration
        return d


def _split_label(label: str) -> tuple[str, str | None, str | None]:
    """'MATRIARCH (O.S.) (Firm)' -> ('dialogue', 'MATRIARCH', 'O.S., Firm')"""
    up = label.strip()
    if up.upper() in NON_DIALOGUE:
        return NON_DIALOGUE[up.upper()], None, None
    speaker = up.split("(")[0].strip()
    tones = re.findall(r"\(([^)]*)\)", up)
    return "dialogue", speaker, ", ".join(tones) or None


def parse_text(text: str, episode_hint: int | None = None) -> Episode:
    lines = text.splitlines()
    ep = Episode(number=episode_hint or 0)
    scene = 0
    i = 0
    raw_beats: list[dict] = []
    while i < len(lines):
        line = lines[i].strip()
        if m := EP_NUM_RE.match(line):
            ep.number = int(m.group(1))
        elif m := LOGLINE_RE.match(line):
            ep.logline = m.group(1).strip()
        elif m := CONT_RE.match(line):
            ep.continuity = m.group(1).strip()
        elif m := SCENE_RE.match(line):
            scene = int(m.group(1))
        elif m := HEADING_RE.match(line):
            ep.scenes[scene] = m.group(1).strip()
        elif m := LABEL_RE.match(line):
            kind, speaker, tone = _split_label(m.group("label"))
            # next non-empty line must be the time line
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            tm = TIME_RE.match(lines[j].strip()) if j < len(lines) else None
            if tm:
                body, k = [], j + 1
                while k < len(lines):
                    nxt = lines[k].strip()
                    if not nxt or LABEL_RE.match(nxt) or SCENE_RE.match(nxt) or nxt.startswith("---"):
                        break
                    body.append(nxt)
                    k += 1
                raw_beats.append(dict(
                    scene=scene, kind=kind, speaker=speaker, tone=tone,
                    start=ts_to_sec(tm.group("s")), end=ts_to_sec(tm.group("e")),
                    text=" ".join(body).strip(),
                ))
                i = k
                continue
        i += 1

    raw_beats.sort(key=lambda b: (b["start"], b["kind"] == "camera"))
    for n, b in enumerate(raw_beats):
        ep.beats.append(Beat(id=f"E{ep.number:02d}-B{n:03d}", episode=ep.number, idx=n, **b))
    return ep


def parse_file(path: str | Path) -> Episode:
    path = Path(path)
    m = FILE_EP_RE.search(path.name)
    return parse_text(path.read_text(encoding="utf-8", errors="replace"),
                      int(m.group(1)) if m else None)


def load_show(source: str | Path) -> dict[int, Episode]:
    """Load every episode from a folder (recursively) or a .zip file."""
    source = Path(source)
    eps: dict[int, Episode] = {}
    if source.suffix.lower() == ".zip":
        with zipfile.ZipFile(source) as z:
            for name in z.namelist():
                if name.lower().endswith(".txt") and not name.startswith("__MACOSX"):
                    m = FILE_EP_RE.search(Path(name).name)
                    txt = io.TextIOWrapper(z.open(name), encoding="utf-8", errors="replace").read()
                    e = parse_text(txt, int(m.group(1)) if m else None)
                    eps[e.number] = e
    elif source.is_dir():
        for p in sorted(source.rglob("*.txt")):
            e = parse_file(p)
            eps[e.number] = e
    else:
        e = parse_file(source)
        eps[e.number] = e
    return dict(sorted(eps.items()))


if __name__ == "__main__":
    import sys
    show = load_show(sys.argv[1])
    for n, e in show.items():
        kinds = {k: sum(b.kind == k for b in e.beats) for k in ("dialogue", "action", "camera", "sfx")}
        print(f"Ep {n:02d}  {sec_to_ts(e.duration)}  beats={len(e.beats)}  {kinds}")
