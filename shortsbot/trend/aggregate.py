"""Turn per-video breakdowns into template.json + missing_assets.txt + a readable report."""
import datetime as dt
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from ..assets import DIRS, AUDIO_EXT, name_matches, norm, TEMPLATE
from ..util import ROOT

HISTORY = ROOT / "trend_history"


def _canon(name):
    return " ".join(w for w in norm(name).split())


def _weights(counter, top=10):
    items = counter.most_common(top)
    total = sum(w for _, w in items) or 1.0
    return {k: w / total for k, w in items}


def _label(name, weight, prev_map, ratio=None):
    p = prev_map.get(_canon(name))
    if ratio is not None and ratio > 1.3:
        return "rising"
    if ratio is not None and ratio < 0.7:
        return "fading"
    if p is None:
        return "new"
    if weight > p * 1.25:
        return "rising"
    if weight < p * 0.75:
        return "fading"
    return "flat"


def _display(variants):
    return Counter(variants).most_common(1)[0][0]


def aggregate(ranked, analyses, tcfg, trends_ratio=None, quota=0):
    trends_ratio = trends_ratio or {}
    score_of = {v["id"]: v["score"] for v in ranked}
    by_id = {v["id"]: v for v in ranked}

    prev = {}
    if TEMPLATE.exists():
        try:
            old = json.loads(TEMPLATE.read_text(encoding="utf-8"))
            prev = {"songs": {_canon(s["name"]): s["weight"] for s in old.get("songs", [])},
                    "sfx": {_canon(s["name"]): s["weight"] for s in old.get("sfx", [])}}
        except Exception:
            pass
    prev.setdefault("songs", {})
    prev.setdefault("sfx", {})

    songs, sfx = Counter(), Counter()
    names = defaultdict(list)
    lengths, popup_pcts, loops = [], [], []
    discovered = Counter()
    for a in analyses:
        w = score_of.get(a["id"], 0.5)
        if a.get("music_song"):
            c = _canon(a["music_song"]); songs[c] += w; names[c].append(a["music_song"])
        if a.get("sfx_name"):
            c = _canon(a["sfx_name"]); sfx[c] += w; names[c].append(a["sfx_name"])
        L = a.get("length_sec")
        if L and 3 <= L <= 90:
            lengths.append(L)
            if a.get("popup_time_sec") is not None and a["popup_time_sec"] <= L:
                popup_pcts.append(a["popup_time_sec"] / L)
        if a.get("loops") is not None:
            loops.append(1 if a["loops"] else 0)
        for d in a.get("discovered", []):
            discovered[_canon(d)] += 1
            names[_canon(d)].append(d)

    sw, fw = _weights(songs), _weights(sfx)

    def items(wmap, kind):
        out = []
        for c, w in wmap.items():
            nm = _display(names[c])
            ratio = trends_ratio.get(nm)
            out.append({"name": nm, "weight": round(w, 4), "trend": _label(nm, w, prev[kind], ratio)})
        return out

    tpl = {
        "updated": dt.date.today().isoformat(),
        "based_on_videos": len(analyses),
        "length_sec": {"median": round(statistics.median(lengths), 1) if lengths else None,
                       "range": [round(min(lengths), 1), round(max(lengths), 1)] if lengths else None},
        "popup_time_pct": {"median": round(statistics.median(popup_pcts), 2) if popup_pcts else None,
                           "samples": len(popup_pcts)},
        "loop_rate": round(sum(loops) / len(loops), 2) if loops else None,
        "songs": items(sw, "songs"),
        "sfx": items(fw, "sfx"),
        "exploration_rate": tcfg["exploration_rate"],
    }

    # --- missing assets: trending but not in your folders
    have_music = [f.stem for f in DIRS["music"].glob("*") if f.suffix.lower() in AUDIO_EXT] if DIRS["music"].exists() else []
    have_sfx = [f.stem for f in DIRS["sfx"].glob("*") if f.suffix.lower() in AUDIO_EXT] if DIRS["sfx"].exists() else []
    missing = []
    for s in tpl["songs"]:
        if s["weight"] >= tcfg["min_weight_for_missing"] and not any(name_matches(s["name"], h) for h in have_music):
            missing.append(f"MUSIC  {s['name']}  (weight {s['weight']:.2f}, {s['trend']})")
    for s in tpl["sfx"]:
        if s["weight"] >= tcfg["min_weight_for_missing"] and not any(name_matches(s["name"], h) for h in have_sfx):
            missing.append(f"SFX    {s['name']}  (weight {s['weight']:.2f}, {s['trend']})")
    new_terms = [_display(names[c]) for c, n in discovered.most_common() if n >= 2][:10]
    return tpl, missing, new_terms


def write_outputs(tpl, missing, new_terms, ranked, quota):
    TEMPLATE.write_text(json.dumps(tpl, indent=2, ensure_ascii=False), encoding="utf-8")
    HISTORY.mkdir(exist_ok=True)
    (HISTORY / f"{tpl['updated']}.json").write_text(json.dumps(tpl, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "missing_assets.txt").write_text(
        "Trending right now but not in your assets/ folders - add these for better results:\n\n"
        + ("\n".join(missing) if missing else "(nothing missing)") + "\n", encoding="utf-8")
    (ROOT / "trend_extra_queries.json").write_text(json.dumps(new_terms), encoding="utf-8")
    learned_p = ROOT / "trend_known_songs.json"
    learned = []
    if learned_p.exists():
        try:
            learned = json.loads(learned_p.read_text(encoding="utf-8"))
        except Exception:
            pass
    for t in new_terms:
        if norm(t) not in {norm(x) for x in learned}:
            learned.append(t)
    learned_p.write_text(json.dumps(learned, indent=1, ensure_ascii=False), encoding="utf-8")

    rep = ROOT / "reports"
    rep.mkdir(exist_ok=True)
    L = [f"# Trend report {tpl['updated']}", "",
         f"Videos analysed: {tpl['based_on_videos']}  |  YouTube quota used: ~{quota} units", "",
         f"Median length: {tpl['length_sec']['median']}s  |  popup at {tpl['popup_time_pct']['median']} of video  "
         f"|  loop rate: {tpl['loop_rate']}", "", "## Songs"]
    L += [f"- {s['name']}: {s['weight']:.2f} ({s['trend']})" for s in tpl["songs"]] or ["- (none identified)"]
    L += ["", "## Sound effects"]
    L += [f"- {s['name']}: {s['weight']:.2f} ({s['trend']})" for s in tpl["sfx"]] or ["- (none identified)"]
    L += ["", "## Newly discovered song names (seen 2+ times)"] + ([f"- {t}" for t in new_terms] or ["- none"])
    L += ["", "## Top outlier videos"]
    for v in ranked[:10]:
        L.append(f"- [{v['title'][:70]}]({v['url']}) - {v['views']:,} views, {v['channel']}, score {v['score']}")
    (rep / f"{tpl['updated']}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return rep / f"{tpl['updated']}.md"
