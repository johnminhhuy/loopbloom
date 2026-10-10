"""Asset library: pick music / meme / sfx, honouring template.json weights and avoiding repeats."""
import json
import random
import re
from pathlib import Path

from .util import ROOT

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
IMAGE_EXT = {".png", ".webp", ".jpg", ".jpeg"}
DIRS = {"music": ROOT / "assets" / "music", "memes": ROOT / "assets" / "memes", "sfx": ROOT / "assets" / "sfx"}
EXTS = {"music": AUDIO_EXT, "memes": IMAGE_EXT, "sfx": AUDIO_EXT}
TEMPLATE = ROOT / "template.json"

NOISE = {"melodica", "cover", "meme", "audio", "sound", "effect", "sfx", "placeholder", "the", "a", "of", "on"}


def norm(s):
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def core_tokens(s):
    return {t for t in norm(s).split() if t not in NOISE}


def name_matches(wanted, filename_stem):
    """Fuzzy: 'Let Me Know' matches 'let_me_know_melodica.mp3'; 'fahhh' matches 'fahh.mp3'."""
    w, f = norm(wanted), norm(filename_stem)
    if not w or not f:
        return False
    if w in f or f in w:
        return True
    wt, ft = core_tokens(wanted), core_tokens(filename_stem)
    if not wt or not ft:
        return False
    if len(wt & ft) / len(wt) >= 0.7:
        return True
    # stretched words: fahhh / fahh / faaah
    squash = lambda t: re.sub(r"(.)\1+", r"\1", t)
    return {squash(t) for t in wt} <= {squash(t) for t in ft}


def list_assets(kind):
    d = DIRS[kind]
    d.mkdir(parents=True, exist_ok=True)
    return sorted(f for f in d.iterdir() if f.suffix.lower() in EXTS[kind])


def load_template():
    if TEMPLATE.exists():
        try:
            return json.loads(TEMPLATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def load_tags():
    p = ROOT / "assets" / "tags.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


TREND_MULT = {"new": 1.6, "rising": 1.5, "peaking": 1.0, "flat": 1.0, "fading": 0.5}


def _weighted(files, items):
    ws = []
    for f in files:
        w = 0.0
        for it in items:
            if name_matches(it["name"], f.stem):
                w += float(it.get("weight", 0)) * TREND_MULT.get(it.get("trend", "flat"), 1.0)
        ws.append(w)
    return ws


def pick(kind, state, cfg, template=None, want_tags=None):
    files = list_assets(kind)
    if not files:
        return None
    recent = set(state.recent(kind, cfg["assets"]["avoid_repeat_last"]))
    pool = [f for f in files if f.name not in recent] or files

    chosen = None
    if kind == "memes" and want_tags:
        tags = load_tags()
        tagged = [f for f in pool if set(want_tags) & {t.lower() for t in tags.get(f.name, [])}]
        if tagged:
            chosen = random.choice(tagged)

    if chosen is None and template:
        items = template.get("songs" if kind == "music" else "sfx" if kind == "sfx" else "_none", [])
        explore = template.get("exploration_rate", cfg["trend"]["exploration_rate"])
        if items and random.random() > explore:
            ws = _weighted(pool, items)
            if sum(ws) > 0:
                chosen = random.choices(pool, weights=ws, k=1)[0]
    if chosen is None:
        chosen = random.choice(pool)
    state.remember_asset(kind, chosen.name)
    return chosen
