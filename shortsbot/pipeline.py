"""One full run: fetch clip -> find moment -> pick assets -> compose -> metadata."""
import json
import random
import shutil
import time
from pathlib import Path

from . import assets, compose, detect, gemini, metadata, sources
from .util import ROOT, ensure_dirs, log, probe


def _plan_window(src_dur, t_moment, vcfg):
    """Always use the WHOLE clip (never cut it). Returns (start, length, t_rel)."""
    length = src_dur
    t_rel = min(max(t_moment, 0.8), max(0.8, length - 0.8))
    return 0.0, length, t_rel


def make_one(cfg, state, mode=None, clip_path=None, loop=None):
    ensure_dirs("work", "output", "inbox")
    vcfg = cfg["video"]
    template = assets.load_template()

    if clip_path:
        clip = sources.from_path(clip_path)
        info = probe(clip.path)
    else:
        clip, info = sources.fetch(cfg, state, mode)
    dur = info["duration"]

    # ---- find the funny moment
    gem = None
    t_moment, method = None, None
    if cfg["detect"]["use_gemini"] and gemini.available():
        try:
            gem = gemini.find_moment(str(clip.path), cfg)
            if 0.3 <= gem["moment_sec"] <= dur:
                t_moment, method = gem["moment_sec"], "gemini"
        except Exception as e:
            log(f"gemini moment detection failed, using audio/motion: {e}")
    if t_moment is None:
        det = detect.find_moment(str(clip.path), dur, cfg["detect"])
        t_moment, method = det["t"], f"{det['method']} (conf {det['confidence']:.2f})"
    log(f"funny moment at {t_moment:.1f}s via {method}")

    # ---- plan (whole clip, never trimmed)
    start, length, t_rel = _plan_window(dur, t_moment, vcfg)
    if length > 180:
        log("WARNING: clip is over 3 minutes - YouTube will not treat it as a Short")

    mode_loop = loop or vcfg["loop"]
    do_loop = mode_loop == "always" or (mode_loop == "auto" and length < vcfg["loop_if_shorter_than"])
    loops = 2 if do_loop else 1
    popup_times = [t_rel + i * length for i in range(loops)]

    # ---- assets
    music = assets.pick("music", state, cfg, template)
    sfx = assets.pick("sfx", state, cfg, template)
    meme = assets.pick("memes", state, cfg, template, want_tags=(gem or {}).get("meme_tags"))
    for kind, a in (("music", music), ("sfx", sfx), ("memes", meme)):
        if a is None:
            log(f"WARNING: no {kind} in assets/{kind}/ - continuing without it")
    log(f"music={getattr(music, 'name', None)} sfx={getattr(sfx, 'name', None)} "
        f"meme={getattr(meme, 'name', None)} len={length:.1f}s loops={loops}")

    # ---- render
    stamp = time.strftime("%Y%m%d_%H%M%S")
    seg = ROOT / "work" / f"seg_{stamp}.mp4"
    out = ROOT / "output" / f"short_{stamp}.mp4"
    compose.prepare_segment(str(clip.path), start, length, seg, vcfg["fps"], info["has_audio"])
    compose.compose(seg, out, music=music, meme=meme, sfx=sfx, popup_times=popup_times,
                    loops=loops, seg_len=length, vcfg=vcfg)
    seg.unlink(missing_ok=True)

    meta = metadata.build(clip, music, sfx, gem, cfg)
    meta.update({"file": out.name, "clip_id": clip.id, "source_url": clip.url,
                 "moment_sec": round(t_moment, 2), "uploaded": False, "youtube_id": None})
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    if not clip_path:
        state.mark_used(clip.id)
    state.d["videos"].append({"file": out.name, "clip_id": clip.id, "uploaded": False})
    state.save()
    # downloaded clips are temporary; local inbox files are left alone
    if clip.source != "local":
        clip.path.unlink(missing_ok=True)
    log(f"done -> {out}")
    return out, meta
