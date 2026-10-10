"""Minimal Gemini REST client (free tier works). Used for moment-finding and trend analysis."""
import base64
import json
import os
import re
import tempfile
import time
from pathlib import Path

import requests

from .util import log, run

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_INLINE = 17 * 1024 * 1024


def available():
    return bool(os.environ.get("GEMINI_API_KEY"))


def shrink(src, out):
    """Make a small copy of the video so it fits in an inline request."""
    for height, crf in ((360, 32), (240, 36)):
        run(["ffmpeg", "-y", "-i", src, "-vf", f"scale=-2:{height},fps=12", "-c:v", "libx264",
             "-crf", str(crf), "-preset", "veryfast", "-c:a", "aac", "-b:a", "40k", "-ac", "1", out])
        if Path(out).stat().st_size < MAX_INLINE:
            return out
    raise RuntimeError("video too large for inline Gemini request")


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)


def generate_json(prompt, video_path=None, cfg=None):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    gcfg = (cfg or {}).get("gemini", {"models": ["gemini-2.5-flash"], "timeout": 120})
    parts = [{"text": prompt}]
    tmp = None
    if video_path:
        tmp = Path(tempfile.mkdtemp()) / "small.mp4"
        shrink(video_path, tmp)
        b64 = base64.b64encode(tmp.read_bytes()).decode()
        parts.insert(0, {"inline_data": {"mime_type": "video/mp4", "data": b64}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    last = None
    for model in gcfg["models"]:
        for attempt in range(3):
            r = requests.post(URL.format(model=model), headers={"x-goog-api-key": key},
                              json=body, timeout=gcfg.get("timeout", 120))
            if r.status_code == 429:
                wait = 15 * (attempt + 1)
                log(f"gemini rate limited, waiting {wait}s")
                time.sleep(wait)
                last = r.text[:200]
                continue
            if r.status_code in (400, 403, 404):
                last = f"{model}: {r.status_code} {r.text[:200]}"
                break  # try next model
            r.raise_for_status()
            try:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
                return _parse_json(txt)
            except Exception as e:
                last = f"bad response from {model}: {e}"
                break
    raise RuntimeError(f"gemini failed: {last}")


MOMENT_PROMPT = """You are helping edit a funny short video. Find the single moment where the funniest
thing happens (the punchline / the fail / the surprise). Return ONLY JSON:
{"moment_sec": <number, seconds from start>, "title": "<short funny title, lowercase, max 8 words>",
 "meme_tags": ["<1-3 words describing the reaction that fits: e.g. shock, facepalm, cry, laugh, chaos>"]}"""


def find_moment(video_path, cfg):
    d = generate_json(MOMENT_PROMPT, video_path, cfg)
    return {"moment_sec": float(d["moment_sec"]), "title": d.get("title", ""),
            "meme_tags": [str(t).lower() for t in d.get("meme_tags", [])]}


MOMENTS_PROMPT = """You are the editor of a comedy Shorts channel. Watch this clip and find the exact moments
an audience would genuinely laugh: the instant the fail, punchline or surprise LANDS (the impact, not the build-up).
Rules:
- Be strict. Rate each moment 1-10 (10 = unmistakably hilarious, 6 = mildly funny, below 6 = not funny).
  Loud noises, camera cuts and plain movement are NOT funny by themselves.
- If nothing is genuinely funny, return an empty list. An empty list is a good answer.
- At most __N__ moments, each at least 3 seconds apart. One strong moment beats several weak ones.
- Seconds are measured from the very start of the video, to one decimal place.
Return ONLY JSON:
{"moments": [{"sec": <number>, "funny": <1-10>, "why": "<max 8 words>"}],
 "title": "<short funny title, lowercase, max 8 words>",
 "meme_tags": ["<1-3 words for a fitting reaction: shock, facepalm, cry, laugh, chaos>"]}"""


def find_moments(video_path, cfg, max_n=3):
    """Ask Gemini for every genuinely funny moment. Returns
    {"moments": [{"sec", "funny", "why"}, ...] (may be empty), "title", "meme_tags"}."""
    d = generate_json(MOMENTS_PROMPT.replace("__N__", str(max_n)), video_path, cfg)
    moments = []
    for m in (d.get("moments") or []):
        try:
            moments.append({"sec": float(m["sec"]), "funny": float(m.get("funny", 5)),
                            "why": str(m.get("why", ""))})
        except Exception:
            continue
    return {"moments": moments, "title": d.get("title", ""),
            "meme_tags": [str(t).lower() for t in d.get("meme_tags", [])]}


ANALYZE_PROMPT = """You are analysing a YouTube Short made in the style: funny clip + background music cover
(e.g. melodica) + a meme image popup with a sound effect (e.g. 'fahhh'). Return ONLY JSON with this shape:
{"length_sec": <number>,
 "music_type": "melodica cover" | "voice cover" | "other" | "none",
 "music_song": "<name of the song being covered, or null>",
 "popup": {"present": true|false, "time_sec": <number or null>, "kind": "reaction image"|"text"|"none",
           "sfx": "<name of the sound effect, e.g. fahhh, vine boom, or null>"},
 "ending": "hard cut" | "loop" | "outro",
 "loops": true|false,
 "caption_style": "none" | "top text" | "subtitles",
 "funny_moment_sec": <number or null>}"""


def analyze_short(video_path, cfg):
    return generate_json(ANALYZE_PROMPT, video_path, cfg)