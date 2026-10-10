"""Test every URL in config.yaml -> source.youtube.queries and report which ones return Shorts.
Run from the shortsbot folder:   py check_channels.py"""
import subprocess, sys
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
queries = cfg.get("source", {}).get("youtube", {}).get("queries", [])
if not queries:
    sys.exit("No source.youtube.queries found in config.yaml")

good, bad = [], []
for q in queries:
    if not q.startswith("http"):
        print(f"SKIP  {q}   (plain search words, not a channel URL)")
        continue
    try:
        r = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "5", "--print", "%(id)s | %(title)s",
                            "--no-warnings", q], capture_output=True, text=True, timeout=90)
    except FileNotFoundError:
        sys.exit("yt-dlp not found. Run:  py -m pip install -U yt-dlp   then reopen the terminal.")
    except subprocess.TimeoutExpired:
        print(f"FAIL  {q}   (timed out)"); bad.append(q); continue
    rows = [l for l in r.stdout.splitlines() if l.strip()]
    if rows:
        print(f"OK    {q}   ({len(rows)} found, e.g. {rows[0][:60]})"); good.append(q)
    else:
        why = (r.stderr.strip().splitlines() or ["no results"])[-1][:90]
        print(f"FAIL  {q}   ({why})"); bad.append(q)

print(f"\n{len(good)} working, {len(bad)} failing. Delete the FAIL lines from config.yaml.")