"""Find the funny moment: audio loudness onsets + visual motion spikes (no heavy deps)."""
import tempfile
from pathlib import Path

import numpy as np

from .util import log, run


def _audio_score(path, dur):
    """Return (times, score) from loudness jumps. Empty arrays if no audio."""
    tmp = Path(tempfile.mkdtemp()) / "a.wav"
    r = run(["ffmpeg", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", tmp], check=False)
    if r.returncode != 0 or not tmp.exists():
        return np.array([]), np.array([])
    from scipy.io import wavfile
    sr, x = wavfile.read(str(tmp))
    x = x.astype(np.float32) / 32768.0
    if len(x) < sr // 2 or float(np.abs(x).max()) < 1e-4:
        return np.array([]), np.array([])
    hop = int(0.05 * sr)
    win = int(0.10 * sr)
    n = max(1, (len(x) - win) // hop)
    rms = np.array([np.sqrt(np.mean(x[i * hop:i * hop + win] ** 2)) for i in range(n)])
    db = 20 * np.log10(rms + 1e-5)
    score = np.zeros(n)
    back = 12  # compare with previous 0.6s
    for i in range(n):
        base = db[max(0, i - back):i].mean() if i > 0 else db[0]
        score[i] = max(0.0, db[i] - base)
    # absolute loudness matters too: quiet "jumps" are boring
    loud = np.clip((db - np.percentile(db, 20)) / 30.0, 0, 1)
    score = score * (0.4 + 0.6 * loud)
    times = (np.arange(n) * hop + win / 2) / sr
    return times, score


def _motion_score(path):
    import cv2
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(fps / 10)))
    prev, diffs, times, i = None, [], [], 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        if i % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                break
            g = cv2.cvtColor(cv2.resize(frame, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
            if prev is not None:
                diffs.append(float(np.mean(np.abs(g - prev))))
                times.append(i / fps)
            prev = g
        i += 1
    cap.release()
    if len(diffs) < 5:
        return np.array([]), np.array([])
    d = np.array(diffs)
    score = np.zeros(len(d))
    for k in range(len(d)):
        base = d[max(0, k - 5):k].mean() if k > 0 else d[0]
        score[k] = max(0.0, d[k] - base)
    return np.array(times), score


def _norm(s):
    if len(s) == 0:
        return s
    hi = np.percentile(s, 99)
    return np.clip(s / hi, 0, 1) if hi > 1e-9 else s * 0


def _composite(path, duration, dcfg):
    """Return (grid, comp, used): a 0..1 'funny-ness' curve sampled every 0.1s."""
    grid = np.arange(0, duration, 0.1)
    comp = np.zeros_like(grid)
    used = []
    ta, sa = _audio_score(path, duration)
    if len(ta):
        comp += dcfg["audio_weight"] * np.interp(grid, ta, _norm(sa))
        used.append("audio")
    try:
        tm, sm = _motion_score(path)
        if len(tm):
            comp += dcfg["motion_weight"] * np.interp(grid, tm, _norm(sm))
            used.append("motion")
    except Exception as e:  # opencv missing etc.
        log(f"motion detection skipped: {e}")
    return grid, comp, used


def find_moments(path, duration, dcfg):
    """Return a list of funny moments, best first: [{"t", "confidence", "method"}, ...].

    Config (all optional, under `detect:`):
      max_popups       most moments to return (1 = single popup)                 default 1
      popup_gap        minimum seconds between two moments                       default 3.0
      extra_threshold  extra moments must reach this fraction of the best one    default 0.6
      extra_min_conf   ...and at least this absolute confidence (0..1)           default 0.3
    """
    grid, comp, used = _composite(path, duration, dcfg)
    if not used:
        return [{"t": duration * 0.5, "confidence": 0.0, "method": "fallback-middle"}]
    lo, hi = dcfg["min_t"], max(dcfg["min_t"] + 0.1, duration - 0.6)
    mask = (grid >= lo) & (grid <= hi)
    if not mask.any():
        return [{"t": duration * 0.5, "confidence": 0.0, "method": "fallback-middle"}]
    total_w = (dcfg["audio_weight"] if "audio" in used else 0) + (dcfg["motion_weight"] if "motion" in used else 0)
    max_n = max(1, int(dcfg.get("max_popups", 1)))
    gap = float(dcfg.get("popup_gap", 3.0))
    rel = float(dcfg.get("extra_threshold", 0.6))
    min_conf = float(dcfg.get("extra_min_conf", 0.3))

    masked = np.where(mask, comp, -1.0)
    out, first = [], None
    while len(out) < max_n:
        i = int(np.argmax(masked))
        peak = float(masked[i])
        if peak <= 0:
            break
        conf = min(1.0, peak / max(total_w, 1e-6))
        if first is None:
            first = peak
        elif peak < rel * first or conf < min_conf:
            break
        out.append({"t": float(grid[i]), "confidence": conf, "method": "+".join(used)})
        masked[(grid >= grid[i] - gap) & (grid <= grid[i] + gap)] = -1.0
    if not out:
        i = int(np.argmax(np.where(mask, comp, -1.0)))
        out.append({"t": float(grid[i]), "confidence": min(1.0, float(comp[i]) / max(total_w, 1e-6)),
                    "method": "+".join(used)})
    return out


def find_moment(path, duration, dcfg):
    """Single best moment (kept for compatibility)."""
    return find_moments(path, duration, {**dcfg, "max_popups": 1})[0]


def refine_many(path, duration, times, dcfg):
    """Gemini's timestamps are only roughly right. Snap each one to the sharpest loudness/motion
    onset within +-snap_radius seconds, i.e. the exact frame of impact. Falls back to the original
    time when there is nothing to snap to."""
    radius = float(dcfg.get("snap_radius", 1.0))
    grid, comp, used = _composite(path, duration, dcfg)
    if not used:
        return list(times)
    out = []
    for t in times:
        m = (grid >= t - radius) & (grid <= t + radius) & (grid >= dcfg["min_t"])
        if not m.any():
            out.append(t)
            continue
        i = int(np.argmax(np.where(m, comp, -1.0)))
        out.append(float(grid[i]) if comp[i] >= 0.15 else t)
    return out