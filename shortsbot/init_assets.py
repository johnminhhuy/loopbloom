"""Create folders + tiny placeholder assets so the pipeline runs before you add real ones."""
import math
import random
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .util import ROOT, ensure_dirs

SR = 44100


def _write_wav(path, x):
    x = np.clip(x, -1, 1)
    data = (x * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(data.tobytes())


def _reed(freq, dur):
    t = np.arange(int(SR * dur)) / SR
    x = sum(a * np.sin(2 * np.pi * freq * k * t) for k, a in ((1, 1), (2, .5), (3, .33), (4, .2)))
    env = np.minimum(1, t / 0.02) * np.exp(-1.2 * t) * 0.6 + 0.2
    return 0.25 * x * env / 2


def make_placeholders():
    ensure_dirs("inbox", "output", "work", "assets/music", "assets/memes", "assets/sfx", "reports")
    m = ROOT / "assets/music/placeholder_melodica_cover.wav"
    if not m.exists():
        notes = [392, 440, 494, 523, 494, 440, 392, 330]
        _write_wav(m, np.concatenate([_reed(f, 0.5) for f in notes] * 2))
    s = ROOT / "assets/sfx/fahhh_placeholder.wav"
    if not s.exists():
        t = np.arange(int(SR * 0.9)) / SR
        f = 420 - 160 * t
        x = 0.8 * np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR)) * np.exp(-2.2 * t)
        _write_wav(s, x * 0.6)
    b = ROOT / "assets/sfx/vine_boom_placeholder.wav"
    if not b.exists():
        t = np.arange(int(SR * 1.0)) / SR
        _write_wav(b, 0.9 * np.sin(2 * np.pi * 55 * t) * np.exp(-4 * t))
    p = ROOT / "assets/memes/placeholder_meme.png"
    if not p.exists():
        img = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle((20, 20, 580, 580), 60, fill=(255, 221, 51, 255), outline=(0, 0, 0, 255), width=12)
        try:
            font = ImageFont.load_default(size=70)
        except TypeError:
            font = ImageFont.load_default()
        d.text((300, 300), "REPLACE\nME", fill=(0, 0, 0, 255), font=font, anchor="mm", align="center")
        img.save(p)


if __name__ == "__main__":
    make_placeholders()
    print("placeholders created")
