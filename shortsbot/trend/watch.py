"""TrendWatcher entry point: collect -> score -> analyse -> aggregate -> template.json."""
import json
import os
import time

from .. import gemini
from ..state import State
from ..util import ROOT, log
from . import aggregate, analyze, collect, identify, score, signals


def run_trends(cfg):
    t = cfg["trend"]
    if not os.environ.get("YOUTUBE_API_KEY"):
        raise RuntimeError("Set YOUTUBE_API_KEY in .env (free key, see README).")

    queries = list(t["queries"])
    extra_p = ROOT / "trend_extra_queries.json"
    if extra_p.exists():
        try:
            extra = json.loads(extra_p.read_text(encoding="utf-8"))[: t["extra_queries_limit"]]
            queries += [f"{e} melodica" for e in extra]
        except Exception:
            pass
    queries = queries[: t["max_searches"]]
    log(f"searching {len(queries)} queries (~{len(queries) * 100} quota units)")

    videos, quota = collect.collect(queries, t["days_back"], t["per_query"], t["max_duration"])
    log(f"{len(videos)} candidate shorts")
    if not videos:
        raise RuntimeError("no videos found - check your API key / queries")
    ranked = score.score(videos, t["keep_top"])

    use_g = gemini.available()
    log("Gemini video breakdown: " + ("ON" if use_g else "OFF (metadata-only; set GEMINI_API_KEY for better results)"))
    known = identify.known_songs()
    analyses = []
    for i, v in enumerate(ranked[: t["analyze_top"]], 1):
        log(f"[{i}/{min(len(ranked), t['analyze_top'])}] {v['title'][:60]}")
        analyses.append(analyze.analyze_video(v, cfg, use_g, known))

    ratios = {}
    if t["track_google_trends"]:
        terms = [s for s in {a["music_song"] for a in analyses if a.get("music_song")}][:10]
        ratios = signals.google_trends(terms) if terms else {}

    tpl, missing, new_terms = aggregate.aggregate(ranked, analyses, t, ratios, quota)
    report = aggregate.write_outputs(tpl, missing, new_terms, ranked, quota)

    st = State()
    st.d["last_trend_run"] = time.time()
    st.save()
    log(f"template.json updated. report: {report}")
    if missing:
        log("add these assets (see missing_assets.txt):")
        for m in missing[:8]:
            log("   " + m)
    return tpl


def template_is_stale(cfg):
    st = State()
    last = st.d.get("last_trend_run")
    return last is None or (time.time() - last) > cfg["trend"]["stale_after_days"] * 86400
