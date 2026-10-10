"""Where clips come from: a local inbox folder, Reddit, or YouTube search (via yt-dlp)."""
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path

import requests

from .util import ROOT, ensure_dirs, have, log, probe, run

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
UA = "Mozilla/5.0 (compatible; shortsbot/1.0; personal hobby project)"


@dataclass
class Clip:
    id: str
    path: Path
    title: str
    credit: str        # human-readable credit line for the description
    source: str
    author: str = ""
    url: str = ""


# ---------------------------------------------------------------- local
def from_path(path):
    p = Path(path)
    return Clip(id=f"local:{p.name}:{p.stat().st_size}", path=p, title=p.stem,
                credit="", source="local")


def fetch_local(cfg, state):
    ensure_dirs("inbox")
    files = [f for f in (ROOT / "inbox").iterdir() if f.suffix.lower() in VIDEO_EXT]
    fresh = [f for f in files if not state.used(from_path(f).id)]
    if not fresh:
        raise RuntimeError("inbox/ has no unused videos. Drop some clips into the inbox/ folder "
                           "(or use --source reddit / youtube).")
    return from_path(random.choice(fresh))


# ---------------------------------------------------------------- yt-dlp helper
def _cookie_args():
    """Optional cookies.txt next to run.py (the GitHub workflow writes it from the YT_COOKIES secret)."""
    c = ROOT / "cookies.txt"
    return ["--cookies", str(c)] if c.exists() else []


def _download(url, out_stem, extra=None):
    if not have("yt-dlp"):
        raise RuntimeError("yt-dlp is not installed (pip install yt-dlp)")
    ensure_dirs("work")
    out = ROOT / "work" / f"{out_stem}.mp4"
    if out.exists():
        out.unlink()
    cmd = ["yt-dlp", "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
           "--no-playlist", "--quiet", "--no-warnings", "-o", out, url]
    cmd[1:1] = _cookie_args() + (extra or [])
    run(cmd)
    if not out.exists():
        raise RuntimeError("download produced no file")
    return out


# ---------------------------------------------------------------- reddit
def fetch_reddit(cfg, state):
    rc = cfg["source"]["reddit"]
    subs = rc["subreddits"][:]
    random.shuffle(subs)
    lo, hi = cfg["source"]["min_seconds"], cfg["source"]["max_seconds"]
    last_err = None
    for sub in subs[:4]:
        url = f"https://www.reddit.com/r/{sub}/top.json?t={rc['time']}&limit={rc['limit']}"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            posts = [c["data"] for c in r.json()["data"]["children"]]
        except Exception as e:
            last_err = e
            log(f"reddit r/{sub} failed: {e}")
            continue
        cands = []
        for p in posts:
            rv = ((p.get("secure_media") or p.get("media") or {}).get("reddit_video")) or {}
            dur = rv.get("duration")
            if not dur or p.get("over_18") or not (lo <= dur <= hi):
                continue
            if state.used("reddit:" + p["id"]):
                continue
            cands.append(p)
        random.shuffle(cands)
        for p in cands[:4]:
            link = "https://www.reddit.com" + p["permalink"]
            try:
                path = _download(link, "reddit_" + p["id"])
            except Exception as e:
                log(f"download failed for {link}: {e}")
                continue
            author = p.get("author", "unknown")
            return Clip(id="reddit:" + p["id"], path=path, title=p.get("title", ""),
                        credit=f"u/{author} on r/{sub} - {link}", source="reddit",
                        author=f"u/{author}", url=link)
    raise RuntimeError(f"no usable reddit clip found (last error: {last_err})")


# ---------------------------------------------------------------- youtube
def fetch_youtube(cfg, state):
    """queries may be plain search words OR full YouTube URLs (a channel's /shorts tab,
    a hashtag page, or a results?search_query=...&sp=... URL with a duration filter)."""
    yc = cfg["source"]["youtube"]
    lo, hi = cfg["source"]["min_seconds"], cfg["source"]["max_seconds"]
    q = random.choice(yc["queries"])
    log(f"youtube source: {q!r}")
    n = yc["search_n"]
    target = q if q.startswith("http") else f"ytsearch{n}:{q}"
    r = run(["yt-dlp", *_cookie_args(), "--flat-playlist", "--playlist-end", str(n), "--dump-json",
             "--quiet", "--no-warnings", target])
    entries = []
    for line in r.stdout.splitlines():
        try:
            entries.append(json.loads(line))
        except Exception:
            pass
    log(f"search returned {len(entries)} entries")
    fresh = [e for e in entries if e.get("id") and not state.used("yt:" + e["id"])]
    known = [e for e in fresh if e.get("duration") and lo <= e["duration"] <= hi]
    unknown = [e for e in fresh if not e.get("duration")]   # checked after download
    log(f"{len(known)} in {lo}-{hi}s, {len(unknown)} with unknown length")
    random.shuffle(known)
    random.shuffle(unknown)
    extra = None
    if yc.get("creative_commons_only"):
        extra = ["--match-filters", "license*=Creative Commons"]
    for e in (known + unknown)[:8]:
        link = f"https://www.youtube.com/watch?v={e['id']}"
        try:
            path = _download(link, "yt_" + e["id"], extra)
            d = probe(path)["duration"]
            if not (lo <= d <= hi):
                path.unlink()
                log(f"skip {e['id']}: {d:.0f}s is outside {lo}-{hi}s")
                continue
        except Exception as ex:
            log(f"skip {e['id']}: {str(ex)[:120]}")
            continue
        who = e.get("channel") or e.get("uploader") or "unknown"
        return Clip(id="yt:" + e["id"], path=path, title=e.get("title", ""),
                    credit=f"{who} - {link}", source="youtube", author=who, url=link)
    raise RuntimeError(f"no usable youtube clip found ({len(entries)} results, "
                       f"{len(known)} in the {lo}-{hi}s range)")


def fetch(cfg, state, mode=None):
    mode = mode or cfg["source"]["mode"]
    fn = {"local": fetch_local, "reddit": fetch_reddit, "youtube": fetch_youtube}[mode]
    clip = fn(cfg, state)
    info = probe(clip.path)
    if not info["has_video"]:
        raise RuntimeError(f"{clip.path} has no video stream")
    log(f"clip: {clip.id} ({info['duration']:.1f}s) {clip.title[:60]!r}")
    return clip, info