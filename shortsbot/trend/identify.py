"""Pull song / sound-effect names out of titles, descriptions and hashtags (no paid fingerprinting)."""
import json
import re
from pathlib import Path

from ..assets import AUDIO_EXT, DIRS, NOISE, norm, name_matches
from ..util import ROOT

SEED_SONGS = [
    "Phoebe", "Let Me Know", "Heaven Knows I'm Miserable Now", "Bazooka", "Ballin", "Jurassic Park",
    "Clutterfunk", "Hey Ya", "Where Is My Husband", "Slide Da Treme", "Deadly P", "After Party",
    "Balls In Ya Jaw", "I Be Poppin Bottles", "Excuse Me Sir", "The Man Behind The Slaughter",
]
SEED_SFX = ["fahhh", "vine boom", "oof", "bruh", "record scratch", "taco bell bong", "metal pipe",
            "sad violin", "airhorn", "wilhelm scream", "dun dun dun", "spongebob fail"]

SFX_PATTERNS = {"fahhh": re.compile(r"\bfa+h+h*\b|\bfaaa+h*\b", re.I)}

_AFTER = re.compile(r"melodica\s*(?:cover\s*)?(?:of\s*)?[:\-–|]?\s*[\"“']?([^#|\"”\n()\[\]]{3,40})", re.I)
_BEFORE = re.compile(r"([^#|\"”\n()\[\]\-–:]{3,40}?)\s+(?:on\s+(?:a\s+)?|\(?)melodica", re.I)
_JUNK = NOISE | {"viral", "shorts", "short", "funny", "trending", "fyp", "tiktok", "on", "in", "my", "i",
                 "this", "that", "is", "it", "hey", "meme", "memes", "song", "songs", "piano", "video"}


def known_songs():
    names = list(SEED_SONGS)
    learned = ROOT / "trend_known_songs.json"          # accumulated by TrendWatcher
    if learned.exists():
        try:
            names += [str(x) for x in json.loads(learned.read_text(encoding="utf-8"))]
        except Exception:
            pass
    d = DIRS["music"]
    if d.exists():
        for f in d.iterdir():
            if f.suffix.lower() in AUDIO_EXT and "placeholder" not in f.stem.lower():
                names.append(re.sub(r"[_\-]+", " ", f.stem).strip())
    seen, out = set(), []
    for n in names:
        if norm(n) not in seen:
            seen.add(norm(n))
            out.append(n)
    return out


def _text(v):
    return " ".join([v.get("title", ""), v.get("description", "")[:600], " ".join(v.get("tags", []))])


def find_songs(v, known=None):
    """Returns (known_matches, discovered_candidates)."""
    known = known or known_songs()
    text = _text(v)
    nt = " " + norm(text) + " "
    hits = [k for k in known if len(norm(k)) >= 4 and f" {norm(k)} " in nt]
    disc = []
    dtext = v.get("title", "") + " . " + v.get("description", "")[:300]
    for rx in (_AFTER, _BEFORE):
        for m in rx.finditer(dtext):
            cand = re.sub(r"\s+", " ", m.group(1)).strip(" -–:|,.!?\"'")
            words = [w for w in norm(cand).split() if w]
            if any(rx2.search(cand) for rx2 in SFX_PATTERNS.values()):
                continue
            if 1 <= len(words) <= 5 and not all(w in _JUNK for w in words):
                cand = " ".join(w for w in cand.split() if norm(w) not in _JUNK) or cand
                if cand and not any(name_matches(cand, k) for k in known):
                    disc.append(cand.title())
    return hits, disc


def find_sfx(v):
    text = _text(v)
    nt = norm(text)
    hits = []
    for name, rx in SFX_PATTERNS.items():
        if rx.search(text):
            hits.append(name)
    for s in SEED_SFX:
        if s not in hits and norm(s) in nt:
            hits.append(s)
    return hits
