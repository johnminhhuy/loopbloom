"""Video composition with plain ffmpeg + Pillow (no moviepy)."""
import math
import random
import shutil
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .util import ROOT, log, run


@lru_cache(maxsize=1)
def _amix_has_normalize():
    r = run(["ffmpeg", "-hide_banner", "-h", "filter=amix"], check=False)
    return "normalize" in (r.stdout + r.stderr)


def prepare_segment(src, start, length, out, fps, has_audio):
    """Trim + normalise the source into a clean mp4 with guaranteed stereo audio."""
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", src]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0",
            "-vf", f"fps={fps},format=yuv420p"]
    if has_audio:
        cmd += ["-af", "aresample=44100,aformat=channel_layouts=stereo"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{length:.3f}", out]
    run(cmd)
    return out


def _has_transparency(img):
    a = np.asarray(img.getchannel("A"))
    return (a < 250).mean() > 0.02


def _blurred_backdrop(img_rgb, W, H, dark=0.8):
    """Screen-sized soft blurred copy of the picture, used behind a meme that doesn't match 9:16."""
    bg = ImageOps.fit(img_rgb, (W // 8, H // 8), Image.BILINEAR).filter(ImageFilter.GaussianBlur(4))
    bg = bg.resize((W, H), Image.BILINEAR)
    return ImageEnhance.Brightness(bg).enhance(dark)


def _layers(img, W, H, fit):
    """Split the meme into (backdrop, foreground-or-None). The backdrop always fills the whole screen.
    cover   -> picture is cropped to fill the screen (nothing behind it, no bars, but edges are cut off)
    contain -> whole picture is visible, backdrop is a blurred copy of it
    auto    -> cover only when the picture is already close to phone-shaped (9:16), otherwise contain"""
    if _has_transparency(img):                              # cut-out PNG: sticker on a tinted backdrop
        arr = np.asarray(img)
        solid = arr[..., 3] > 200
        avg = tuple(int(c) for c in arr[..., :3][solid].mean(axis=0)) if solid.any() else (40, 40, 40)
        flat = Image.new("RGB", img.size, avg)
        flat.paste(img, mask=img.getchannel("A"))
        sc = min(W * 0.96 / img.width, H * 0.8 / img.height)
        fg = img.resize((max(2, int(img.width * sc)), max(2, int(img.height * sc))), Image.LANCZOS)
        return _blurred_backdrop(flat, W, H), fg
    rgb = img.convert("RGB")
    ratio = img.width / img.height
    mode = fit if fit in ("cover", "contain") else ("cover" if 0.5 <= ratio <= 0.65 else "contain")
    if mode == "cover":
        return ImageOps.fit(rgb, (W, H), Image.LANCZOS), None
    sc = min(W / img.width, H / img.height)
    fg = rgb.resize((max(2, int(img.width * sc)), max(2, int(img.height * sc))), Image.LANCZOS)
    return _blurred_backdrop(rgb, W, H), fg


def make_pop_frames(meme_path, out_dir, W, H, fps, duration, pc):
    """Pre-render the hit as a PNG sequence: white-out flash -> zoom punch -> screen shake -> hard cut."""
    img = Image.open(meme_path)
    img = ImageOps.exif_transpose(img).convert("RGBA")      # phone photos: honour rotation tag
    rng = random.Random(7)
    punch, shake = pc["punch_scale"], pc["shake_px"]
    hold = pc["flash_hold_frames"] if pc["flash"] else 0
    hold_t = hold / fps
    fullscreen = pc["fullscreen"]
    if fullscreen:
        backdrop, fg = _layers(img, W, H, pc.get("fit", "auto"))
    n = max(3, int(round(duration * fps)))
    for i in range(n):
        t = i / fps
        s = 1.0 + (punch - 1.0) * math.exp(-t * 18)          # snap from big to normal
        amp = shake * math.exp(-t * 9)                        # shake dies out in ~0.3s
        dx, dy = rng.uniform(-amp, amp), rng.uniform(-amp, amp)
        rot = rng.uniform(-1, 1) * 2.0 * math.exp(-t * 10)
        if fullscreen:
            # backdrop only needs spare edge while it is shaking/rotating, so at rest nothing is cropped
            margin = 1.0 + (2 * amp + 2 * H * math.sin(math.radians(abs(rot))) + 4) / W
            cover = margin * (s if fg is None else 1.0)
            bg = backdrop.resize((int(W * cover), int(H * cover)), Image.LANCZOS)
            if abs(rot) > 0.05:
                bg = bg.rotate(rot, resample=Image.BICUBIC)
            l = min(max(int((bg.width - W) / 2 + dx), 0), bg.width - W)
            u = min(max(int((bg.height - H) / 2 + dy), 0), bg.height - H)
            frame = bg.crop((l, u, l + W, u + H)).convert("RGBA")
            if fg is not None:
                m = fg.convert("RGBA")
                if s != 1.0:
                    m = m.resize((max(2, int(m.width * s)), max(2, int(m.height * s))), Image.LANCZOS)
                if abs(rot) > 0.05:
                    m = m.rotate(rot, resample=Image.BICUBIC, expand=True)
                frame.alpha_composite(m, (int((W - m.width) / 2 + dx), int((H - m.height) / 2 + dy))) \
                    if (W - m.width) / 2 + dx >= 0 and (H - m.height) / 2 + dy >= 0 else \
                    frame.paste(m, (int((W - m.width) / 2 + dx), int((H - m.height) / 2 + dy)), m)
        else:
            w0 = int(W * pc["width_frac"])
            m = img.resize((w0, max(2, int(img.height * w0 / img.width))), Image.LANCZOS)
            m = m.resize((max(2, int(m.width * s)), max(2, int(m.height * s))), Image.LANCZOS)
            m = m.rotate(rot * 2, resample=Image.BICUBIC, expand=True)
            frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            frame.paste(m, (int((W - m.width) / 2 + dx), int(H * pc["y_frac"] - m.height / 2 + dy)), m)
        if t < 0.12:                                          # hit looks over-exposed for a moment
            k = 1 - t / 0.12
            rgb = frame.convert("RGB")
            rgb = ImageEnhance.Brightness(rgb).enhance(1 + 0.5 * k)
            rgb = ImageEnhance.Contrast(rgb).enhance(1 + 0.3 * k)
            if frame.mode == "RGBA":
                rgb.putalpha(frame.getchannel("A"))
            frame = rgb
        if pc["flash"]:
            wa = 1.0 if i < hold else max(0.0, 1.0 - (t - hold_t) * 6.0)
            if wa > 0:
                white = Image.new("RGBA", (W, H), (255, 255, 255, int(255 * wa)))
                frame = Image.alpha_composite(frame.convert("RGBA"), white)
        # every frame must have the same pixel format (RGBA), or ffmpeg re-inits mid-stream and loses frames
        frame.convert("RGBA").save(Path(out_dir) / f"pop_{i:03d}.png", compress_level=1)
    return n


def compose(seg, out, *, music, meme, sfx, popup_times, loops, seg_len, vcfg):
    """seg: prepared segment. popup_times: seconds (in final timeline). Returns output path."""
    W, H, fps = vcfg["width"], vcfg["height"], vcfg["fps"]
    pc = vcfg["popup"]
    total = seg_len * loops
    pdur = pc["duration"]
    work = Path(tempfile.mkdtemp(prefix="pop_", dir=str(ROOT / "work")))
    try:
        frames = None
        if meme:
            make_pop_frames(meme, work, W, H, fps, pdur, pc)

        cmd = ["ffmpeg", "-y"]
        if loops > 1:
            cmd += ["-stream_loop", str(loops - 1)]
        cmd += ["-i", seg]                                        # input 0: video+audio
        idx = 1
        music_idx = None
        if music:
            cmd += ["-stream_loop", "-1", "-i", music]
            music_idx, idx = idx, idx + 1
        pop_idx = []
        if meme:
            for _ in popup_times:
                cmd += ["-framerate", str(fps), "-i", str(work / "pop_%03d.png")]
                pop_idx.append(idx)
                idx += 1
        sfx_idx = []
        if sfx:
            for _ in popup_times:
                cmd += ["-i", sfx]
                sfx_idx.append(idx)
                idx += 1

        f = []
        f.append("[0:v]split=2[bgsrc][fgsrc]")
        f.append("[bgsrc]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                 "boxblur=8:2,eq=brightness=-0.2:saturation=0.9,scale=%d:%d,setsar=1[bg]" % (W, H))
        f.append("[fgsrc]scale=%d:%d:force_original_aspect_ratio=decrease,"
                 "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[fg]" % (W, H))
        f.append("[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]")
        last = "v0"
        for k, (T, pi) in enumerate(zip(popup_times, pop_idx)):
            f.append(f"[{pi}:v]format=rgba,setpts=PTS-STARTPTS+{T:.3f}/TB[pop{k}]")
            f.append(f"[{last}][pop{k}]overlay=x=0:y=0:"
                     f"enable='between(t,{T:.3f},{T + pdur:.3f})':eof_action=pass[v{k + 1}]")
            last = f"v{k + 1}"
        f.append(f"[{last}]format=yuv420p[vout]")

        # ---- audio (clip + music duck under the hit so the sfx slams)
        duck_level, duck_len = pc.get("duck", 1.0), pc.get("duck_len", 0.6)
        expr = ""
        if duck_level < 1.0 and popup_times:
            terms = [f"between(t,{T:.3f},{T + duck_len:.3f})" for T in popup_times]
            expr = terms[0]
            for tm in terms[1:]:
                expr = f"max({expr},{tm})"

        def vol(base):
            if expr:
                return f"volume='{base}*(1-{1 - duck_level:.3f}*{expr})':eval=frame"
            return f"volume={base}"

        fmt = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
        labels = []
        if not vcfg.get("mute_original"):
            f.append(f"[0:a]{fmt},{vol(vcfg['original_volume'])}[a0]")
            labels.append("a0")
        if music_idx is not None:
            fo = max(0.0, total - 0.4)
            f.append(f"[{music_idx}:a]{fmt},{vol(vcfg['music_volume'])},afade=t=out:st={fo:.3f}:d=0.4[am]")
            labels.append("am")
        for k, (T, si) in enumerate(zip(popup_times, sfx_idx)):
            ms = int(T * 1000)
            f.append(f"[{si}:a]{fmt},adelay={ms}|{ms},volume={vcfg['sfx_volume']}[s{k}]")
            labels.append(f"s{k}")
        n = len(labels)
        if n == 0:
            f.append("anullsrc=r=44100:cl=stereo[aout]")
        elif _amix_has_normalize():
            f.append("".join(f"[{l}]" for l in labels) + f"amix=inputs={n}:duration=longest:normalize=0,"
                     "alimiter=limit=0.95[aout]")
        else:
            f.append("".join(f"[{l}]" for l in labels) + f"amix=inputs={n}:duration=longest,volume={n},"
                     "alimiter=limit=0.95[aout]")

        cmd += ["-filter_complex", ";".join(f), "-map", "[vout]", "-map", "[aout]",
                "-t", f"{total:.3f}", "-r", str(fps), "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
        run(cmd)
        return Path(out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
