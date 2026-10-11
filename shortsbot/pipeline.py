"""One full run: fetch clip -> find moment -> pick assets -> compose -> metadata."""
import json
import random
import shutil
import time
from pathlib import Path

from . import assets, compose, detect, gemini, metadata, sources
from .util import ROOT, ensure_dirs, log, probe


def _plan_window(src_dur, t_moment, target_len, popup_pct, vcfg):
    """Choose (start, length, t_rel): which part of the clip to use and where the popup lands in it."""
    length = min(src_dur, target_len, vcfg["max_len"])
    if src_dur <= target_len:
        start = 0.0
    else:
        start = min(max(0.0, t_moment - popup_pct * length), src_dur - length)
    t_rel = t_moment - start
    t_rel = min(max(t_rel, 0.8), max(0.8, length - 0.8))
    return start, length, t_rel


def _plan_window_multi(src_dur, peaks, target_len, popup_pct, vcfg):
    """peaks: [(t, score), ...] best first. Pick the window that covers the most funny-ness and
    return (start, length, [t_rel, ...]) with one popup time per covered moment."""
    start, length, t_rel = _plan_window(src_dur, peaks[0][0], target_len, popup_pct, vcfg)
    if len(peaks) == 1:
        return start, length, [t_rel]
    if src_dur <= length:
        cands = [0.0]
    else:
        cands = {start}
        for t, _ in peaks:
            cands.add(min(max(0.0, t - popup_pct * length), src_dur - length))
    best = None
    for c in cands:
        covered = [(t - c, sc) for t, sc in peaks if 0.8 <= t - c <= length - 0.8]
        total = sum(sc for _, sc in covered)
        if covered and (best is None or total > best[0] + 1e-9):
            best = (total, c, sorted(r for r, _ in covered))
    if best is None:
        return start, length, [t_rel]
    return best[1], length, best[2]


def _local_peaks(clip, dur, dcfg):
    dets = detect.find_moments(str(clip.path), dur, dcfg)
    return ([(d["t"], d["confidence"]) for d in dets],
            f"{dets[0]['method']} (conf {dets[0]['confidence']:.2f})")


def _find_peaks(cfg, clip, dur, at=None):
    """Return (peaks, method, gem). peaks = [(t, score), ...] best first; EMPTY means
    'Gemini watched it and found nothing funny'."""
    dcfg = cfg["detect"]
    if at:
        peaks = [(t, 1.0) for t in at if 0.3 <= t <= dur]
        if not peaks:
            raise RuntimeError(f"--at times {at} are outside the clip (0-{dur:.1f}s)")
        return peaks, "manual (--at)", None
    if dcfg["use_gemini"] and gemini.available():
        try:
            max_n = max(1, int(dcfg.get("max_popups", 3)))
            res = gemini.find_moments(str(clip.path), cfg, max_n=max_n)
            for m in res["moments"]:
                log(f"gemini: {m['sec']:.1f}s funny={m['funny']:.0f}/10 - {m['why']}")
            floor = float(dcfg.get("min_funny", 6))
            keep = sorted((m for m in res["moments"] if m["funny"] >= floor and 0.3 <= m["sec"] <= dur),
                          key=lambda m: -m["funny"])
            gem = {"title": res["title"], "meme_tags": res["meme_tags"]}
            if not keep:
                return [], "gemini: nothing funny", gem
            keep = keep[:max_n]
            try:
                snapped = detect.refine_many(str(clip.path), dur, [m["sec"] for m in keep], dcfg)
            except Exception as e:
                log(f"snap-to-impact skipped: {e}")
                snapped = [m["sec"] for m in keep]
            gap = float(dcfg.get("popup_gap", 3.0))
            peaks = []
            for t, m in zip(snapped, keep):
                if all(abs(t - pt) >= gap for pt, _ in peaks):
                    peaks.append((t, m["funny"] / 10.0))
            gem["moment_sec"] = peaks[0][0]
            return peaks, "gemini", gem
        except Exception as e:
            log(f"gemini moment detection failed, using audio/motion instead: {e}")
    peaks, method = _local_peaks(clip, dur, dcfg)
    return peaks, method, None


def make_one(cfg, state, mode=None, clip_path=None, loop=None, at=None):
    ensure_dirs("work", "output", "inbox")
    vcfg = cfg["video"]
    template = assets.load_template()

    tries = 1 if clip_path else max(1, int(cfg["detect"].get("max_clip_tries", 4)))
    for _ in range(tries):
        if clip_path:
            clip = sources.from_path(clip_path)
            info = probe(clip.path)
        else:
            clip, info = sources.fetch(cfg, state, mode)
        dur = info["duration"]
        peaks, method, gem = _find_peaks(cfg, clip, dur, at)
        if peaks:
            break
        if clip_path:   # you chose this file yourself, so use its loudest moment anyway
            log("gemini saw nothing funny, but you picked this clip, so using its loudest moment")
            peaks, method = _local_peaks(clip, dur, cfg["detect"])
            break
        log("not funny enough - skipping this clip and trying another")
        state.mark_used(clip.id)
        state.save()
        if clip.source != "local":
            clip.path.unlink(missing_ok=True)
    else:
        raise RuntimeError(f"no funny clip found after {tries} tries "
                           f"(lower detect.min_funny, or try other channels in config.yaml)")
    t_moment = peaks[0][0]
    log(f"funny moment at {t_moment:.1f}s via {method}")
    if len(peaks) > 1:
        log("all moments: " + ", ".join(f"{t:.1f}s ({sc:.2f})" for t, sc in peaks))

    # ---- plan
    tl = template.get("length_sec", {}).get("median")
    target_len = min(max(tl or vcfg["default_len"], vcfg["min_len"]), vcfg["max_len"])
    popup_pct = template.get("popup_time_pct", {}).get("median") or 0.5
        # always use the WHOLE clip (never cut it)
    target_len = dur
    vcfg = {**vcfg, "max_len": max(vcfg["max_len"], dur)}
    if at:   # you picked the moments, so stretch the video to hold all of them (Shorts max ~59s)
        ts = [t for t, _ in peaks]
        need = (max(ts) - min(ts)) + 6.0
        if need > target_len:
            target_len = min(need, 59.0, dur)
            vcfg = {**vcfg, "max_len": max(vcfg["max_len"], target_len)}
            log(f"--at: video stretched to {target_len:.0f}s to fit all your moments")
    pc = vcfg["popup"]
    tail = 0.0
    if pc.get("at", "moment") == "end":
        # meme-at-the-end mode: the clip plays, the funny thing happens, a short beat passes,
        # then the meme + sound effect slam in as the final frame.
        after = float(pc.get("end_after", 1.5))     # seconds of clip kept AFTER the funny moment (the beat)
        tail = float(pc.get("end_hold", 1.6))       # how long the meme sits at the end
        punchline = max(t for t, _ in peaks) if at else t_moment   # with --at, the LAST time you gave
        end_t = min(dur, punchline + after)
        start = max(0.0, end_t - target_len)
        min_len = float(vcfg.get("min_len", 6))
        if end_t - start < min_len:        # funny moment came early: keep more of what follows it
            end_t = min(dur, start + min_len)
        length = max(2.0, end_t - start)
        start = max(0.0, min(start, dur - length))
        rels = [length]                             # meme starts the instant the clip ends
        loops = 1
        popup_times = [length]
        log(f"meme-at-the-end: clip {start:.1f}s-{start + length:.1f}s, then meme for {tail:.1f}s")
    else:
        start, length, rels = _plan_window_multi(dur, peaks, target_len, popup_pct, vcfg)
        mode_loop = loop or vcfg["loop"]
        do_loop = mode_loop == "always" or (mode_loop == "auto" and length < vcfg["loop_if_shorter_than"])
        loops = 2 if do_loop else 1
        popup_times = [r + i * length for i in range(loops) for r in rels]

    # ---- assets
    music = assets.pick("music", state, cfg, template)
    sfx = assets.pick("sfx", state, cfg, template)
    meme = assets.pick("memes", state, cfg, template, want_tags=(gem or {}).get("meme_tags"))
    for kind, a in (("music", music), ("sfx", sfx), ("memes", meme)):
        if a is None:
            log(f"WARNING: no {kind} in assets/{kind}/ - continuing without it")
    log(f"music={getattr(music, 'name', None)} sfx={getattr(sfx, 'name', None)} "
        f"meme={getattr(meme, 'name', None)} len={length:.1f}s loops={loops} popups={len(rels)}")

    # ---- render
    stamp = time.strftime("%Y%m%d_%H%M%S")
    seg = ROOT / "work" / f"seg_{stamp}.mp4"
    out = ROOT / "output" / f"short_{stamp}.mp4"
    compose.prepare_segment(str(clip.path), start, length, seg, vcfg["fps"], info["has_audio"])
    compose.compose(seg, out, music=music, meme=meme, sfx=sfx, popup_times=popup_times,
                    loops=loops, seg_len=length, vcfg=vcfg, tail=tail)
    seg.unlink(missing_ok=True)

    meta = metadata.build(clip, music, sfx, gem, cfg)
    meta.update({"file": out.name, "clip_id": clip.id, "source_url": clip.url,
                 "moment_sec": round(t_moment, 2), "popups_at": [round(r + start, 2) for r in rels], "uploaded": False, "youtube_id": None})
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