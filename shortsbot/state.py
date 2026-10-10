"""Persistent state: used clips, recently used assets, produced videos."""
import json
import os
import tempfile
from .util import ROOT

PATH = ROOT / "state.json"


class State:
    def __init__(self):
        self.d = {"used_clips": [], "recent": {"music": [], "memes": [], "sfx": []},
                  "videos": [], "last_trend_run": None}
        if PATH.exists():
            try:
                self.d.update(json.loads(PATH.read_text(encoding="utf-8")))
            except Exception:
                pass

    def save(self):
        fd, tmp = tempfile.mkstemp(dir=str(ROOT), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.d, f, indent=2, ensure_ascii=False)
        os.replace(tmp, PATH)

    def used(self, clip_id):
        return clip_id in self.d["used_clips"]

    def mark_used(self, clip_id):
        if clip_id not in self.d["used_clips"]:
            self.d["used_clips"].append(clip_id)

    def remember_asset(self, kind, name, keep=30):
        r = self.d["recent"].setdefault(kind, [])
        r.append(name)
        del r[:-keep]

    def recent(self, kind, n):
        return self.d["recent"].get(kind, [])[-n:]
