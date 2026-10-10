"""Rank videos by how much they over-perform (views vs channel size, and views per hour)."""
import datetime as dt


def _ranks(values):
    """Percentile rank in [0,1] for each value (ties share the lower rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    for pos, i in enumerate(order):
        out[i] = pos / max(1, len(values) - 1)
    return out


def score(videos, keep, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    for v in videos:
        pub = dt.datetime.fromisoformat(v["published"].replace("Z", "+00:00"))
        hours = max(1.0, (now - pub).total_seconds() / 3600)
        v["hours_old"] = round(hours, 1)
        v["vph"] = v["views"] / hours
        v["outlier"] = v["views"] / max(v["subs"], 1000) if v.get("subs") is not None else None
    if not videos:
        return []
    vph_rank = _ranks([v["vph"] for v in videos])
    out_rank = _ranks([v["outlier"] if v["outlier"] is not None else v["vph"] for v in videos])
    for v, a, b in zip(videos, vph_rank, out_rank):
        v["score"] = round(0.55 * b + 0.45 * a, 4)
    return sorted(videos, key=lambda v: v["score"], reverse=True)[:keep]
