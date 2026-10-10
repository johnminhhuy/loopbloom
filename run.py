
"""ShortsBot - auto-make funny YouTube Shorts (clip + melodica + meme popup + sfx).

  python run.py init                 create folders + placeholder assets
  python run.py doctor               check your setup
  python run.py make                 make one video (from the configured source)
  python run.py make --clip file.mp4 make one from a specific file
  python run.py trends               update template.json from what's trending
  python run.py upload               upload every un-uploaded video in output/
  python run.py daily --count 3 --upload
"""
import argparse
import json
import os
import sys
import time

from shortsbot.config import load_config
from shortsbot.util import ROOT, ensure_dirs, ffmpeg_info, have, load_env, log, use_local_ffmpeg


def cmd_init(a, cfg):
    from shortsbot.init_assets import make_placeholders
    make_placeholders()
    log("folders created. Put real files in assets/music, assets/memes, assets/sfx (see README).")
    log("Put clips you want to use in inbox/ (or use --source reddit / youtube).")


def cmd_doctor(a, cfg):
    from shortsbot import assets, gemini
    ok = True
    fok, ftxt = ffmpeg_info()
    print(f"{'OK ' if fok else 'BAD'} ffmpeg version: {ftxt}")
    if not fok:
        print("    -> need a modern ffmpeg. Download 'release essentials' from https://www.gyan.dev/ffmpeg/builds/,")
        print(f"       unzip it INSIDE {ROOT} (so you get a folder like ffmpeg-7.1-essentials_build) and run doctor again.")
        ok = False
    for tool in ("ffmpeg", "ffprobe", "yt-dlp"):
        h = have(tool)
        print(f"{'OK ' if h else 'MISSING'} {tool}" + ("" if h else "   <- needed" if tool != "yt-dlp" else "   <- needed for reddit/youtube sources"))
        ok &= h or tool == "yt-dlp"
    for kind in ("music", "memes", "sfx"):
        files = assets.list_assets(kind)
        real = [f for f in files if "placeholder" not in f.name.lower()]
        flag = "OK " if real else "WARN"
        print(f"{flag} assets/{kind}: {len(real)} real file(s)" + ("  (only placeholders - add real ones)" if files and not real else ""))
    for key, why in (("GEMINI_API_KEY", "smarter moment detection + trend analysis (optional)"),
                     ("YOUTUBE_API_KEY", "TrendWatcher (optional)")):
        print(f"{'OK ' if os.environ.get(key) else 'off'} {key}: {why}")
    from shortsbot.upload import have_env_credentials
    if have_env_credentials():
        print("OK  YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN: headless upload credentials set")
    else:
        print(f"{'OK ' if (ROOT / cfg['upload']['client_secret']).exists() else 'off'} {cfg['upload']['client_secret']}: needed for uploading (or set YT_* env vars)")
    print(f"{'OK ' if (ROOT / 'template.json').exists() else 'off'} template.json: created by `python run.py trends`")
    sys.exit(0 if ok else 1)


def _make(cfg, a, count):
    fok, ftxt = ffmpeg_info()
    if not fok:
        log(f"ffmpeg problem: {ftxt}. Run `py run.py doctor` for the fix.")
        sys.exit(1)
    from shortsbot.pipeline import make_one
    from shortsbot.state import State
    st = State()
    made = []
    for i in range(count):
        try:
            out, meta = make_one(cfg, st, mode=a.source, clip_path=getattr(a, "clip", None), loop=a.loop)
            made.append((out, meta))
        except Exception as e:
            log(f"video {i + 1} failed: {e}")
        time.sleep(1.1)  # keeps filenames unique
    return made


def _upload_pending(cfg):
    from shortsbot.state import State
    from shortsbot.upload import upload
    st = State()
    n = 0
    for js in sorted((ROOT / "output").glob("*.json")):
        meta = json.loads(js.read_text(encoding="utf-8"))
        mp4 = js.with_suffix(".mp4")
        if meta.get("uploaded") or not mp4.exists():
            continue
        try:
            vid = upload(mp4, meta, cfg)
        except Exception as e:
            log(f"upload failed for {mp4.name}: {e}")
            break
        meta.update(uploaded=True, youtube_id=vid)
        js.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        for v in st.d["videos"]:
            if v["file"] == mp4.name:
                v.update(uploaded=True, youtube_id=vid)
        st.save()
        n += 1
    log(f"uploaded {n} video(s)")


def cmd_make(a, cfg):
    made = _make(cfg, a, a.count)
    if a.upload and made:
        _upload_pending(cfg)


def cmd_upload(a, cfg):
    _upload_pending(cfg)


def cmd_auth(a, cfg):
    from shortsbot.upload import credentials, print_secrets
    creds = credentials(cfg)
    log("authorised. token saved.")
    print_secrets(creds)


def cmd_trends(a, cfg):
    from shortsbot.trend.watch import run_trends
    run_trends(cfg)


def cmd_daily(a, cfg):
    from shortsbot.trend.watch import run_trends, template_is_stale
    if os.environ.get("YOUTUBE_API_KEY") and template_is_stale(cfg):
        try:
            run_trends(cfg)
        except Exception as e:
            log(f"trend update failed (continuing with the old template): {e}")
    made = _make(cfg, a, a.count)
    if a.upload and made:
        _upload_pending(cfg)


def main():
    load_env()
    use_local_ffmpeg()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("doctor")
    sub.add_parser("auth")
    sub.add_parser("trends")
    sub.add_parser("upload")
    for name in ("make", "daily"):
        p = sub.add_parser(name)
        p.add_argument("--source", choices=["local", "reddit", "youtube"])
        p.add_argument("--count", type=int, default=1)
        p.add_argument("--loop", choices=["auto", "always", "never"])
        p.add_argument("--upload", action="store_true")
        if name == "make":
            p.add_argument("--clip", help="use this specific video file")
    a = ap.parse_args()
    ensure_dirs("inbox", "output", "work")
    cfg = load_config()
    {"init": cmd_init, "doctor": cmd_doctor, "make": cmd_make, "upload": cmd_upload, "auth": cmd_auth,
     "trends": cmd_trends, "daily": cmd_daily}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
