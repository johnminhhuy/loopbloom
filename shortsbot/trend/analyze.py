"""Break each winning Short down into its 'form'. Gemini (free tier) when available, else metadata only."""
import json
import time
from pathlib import Path

from .. import gemini
from ..util import ROOT, ensure_dirs, have, log, run
from . import identify

CACHE = ROOT / "trend_cache"


def _download_small(v):
    ensure_dirs("work")
    out = ROOT / "work" / f"trend_{v['id']}.mp4"
    if out.exists():
        out.unlink()
    run(["yt-dlp", "-f", "b[height<=480]/worst", "--no-playlist", "--quiet", "--no-warnings",
         "-o", out, v["url"]])
    return out


def analyze_video(v, cfg, use_gemini, known):
    CACHE.mkdir(exist_ok=True)
    cp = CACHE / f"{v['id']}.json"
    if cp.exists():
        return json.loads(cp.read_text(encoding="utf-8"))

    songs, disc = identify.find_songs(v, known)
    sfx = identify.find_sfx(v)
    res = {"id": v["id"], "length_sec": v["duration"], "music_song": songs[0] if songs else None,
           "songs_found": songs, "discovered": disc, "sfx_name": sfx[0] if sfx else None,
           "popup_time_sec": None, "loops": None, "gemini": False}

    if use_gemini and have("yt-dlp"):
        path = None
        try:
            path = _download_small(v)
            g = gemini.analyze_short(str(path), cfg)
            time.sleep(cfg["gemini"]["delay_between_calls"])
            res["gemini"] = True
            pop = g.get("popup") or {}
            if pop.get("present") and isinstance(pop.get("time_sec"), (int, float)):
                res["popup_time_sec"] = float(pop["time_sec"])
            if pop.get("sfx") and not res["sfx_name"]:
                res["sfx_name"] = str(pop["sfx"]).lower()
            if g.get("music_song") and not res["music_song"]:
                res["music_song"] = str(g["music_song"])
            res["loops"] = bool(g.get("loops")) or g.get("ending") == "loop"
            res["music_type"] = g.get("music_type")
            if isinstance(g.get("length_sec"), (int, float)) and g["length_sec"] > 0:
                res["length_sec"] = float(g["length_sec"])
        except Exception as e:
            log(f"  gemini analysis failed for {v['id']}: {str(e)[:160]}")
        finally:
            if path:
                Path(path).unlink(missing_ok=True)
    cp.write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res
