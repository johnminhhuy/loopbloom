"""Small shared helpers: logging, subprocess, ffprobe, .env loading."""
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def log(*a):
    print("[shortsbot]", *a, flush=True)


def load_env(path=None):
    """Load KEY=VALUE lines from .env into os.environ (does not override real env vars)."""
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def run(cmd, check=True):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(str(c) for c in cmd[:4])} ...\n{(r.stderr or '')[-1800:]}")
    return r


def use_local_ffmpeg():
    """If you unzipped an ffmpeg build inside the project folder (e.g. D:\\shortsbot\\ffmpeg-7.1-essentials_build),
    put it first on PATH so it wins over any old ffmpeg installed elsewhere."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    cands = (list(ROOT.glob("ffmpeg*/bin")) + list(ROOT.glob("ffmpeg*/*/bin"))
             + list(ROOT.glob("ffmpeg*")) + list(ROOT.glob("ffmpeg*/*")))
    for d in cands:
        if d.is_dir() and (d / exe).exists():
            os.environ["PATH"] = str(d) + os.pathsep + os.environ.get("PATH", "")
            return d
    return None


def ffmpeg_info():
    """Return (ok, text). ok is False if ffmpeg is missing or too old (libavfilter < 7, i.e. before 2018)."""
    import re
    if not have("ffmpeg"):
        return False, "ffmpeg not found"
    r = run(["ffmpeg", "-version"], check=False)
    out = (r.stdout or "") + (r.stderr or "")
    first = out.splitlines()[0] if out else "unknown version"
    m = re.search(r"libavfilter\s+(\d+)", out)
    if m and int(m.group(1)) < 7:
        return False, f"TOO OLD: {first}"
    return True, first


def have(tool):
    return shutil.which(tool) is not None


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path])
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    dur = float(d.get("format", {}).get("duration") or (v or {}).get("duration") or 0)
    return {
        "duration": dur,
        "width": int(v["width"]) if v else 0,
        "height": int(v["height"]) if v else 0,
        "has_audio": a is not None,
        "has_video": v is not None,
    }


def ensure_dirs(*names):
    for n in names:
        (ROOT / n).mkdir(parents=True, exist_ok=True)
