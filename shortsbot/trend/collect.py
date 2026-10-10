"""Collect recent short videos for tracked queries via the YouTube Data API v3 (free API key)."""
import datetime as dt
import os
import re

import requests

API = "https://www.googleapis.com/youtube/v3"


def _get(path, params):
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY not set (see README)")
    r = requests.get(f"{API}/{path}", params={**params, "key": key}, timeout=30)
    if r.status_code == 403 and "quota" in r.text.lower():
        raise RuntimeError("YouTube API quota exhausted for today - try again tomorrow")
    r.raise_for_status()
    return r.json()


def iso_duration(s):
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return 0
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def collect(queries, days_back, per_query, max_duration, get=_get):
    """Returns (videos, quota_units_used)."""
    after = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_back)).strftime("%Y-%m-%dT%H:%M:%SZ")
    quota = 0
    found = {}
    for q in queries:
        res = get("search", {"part": "snippet", "q": q, "type": "video", "videoDuration": "short",
                             "order": "viewCount", "publishedAfter": after, "maxResults": min(50, per_query)})
        quota += 100
        for it in res.get("items", []):
            vid = it["id"].get("videoId")
            if vid and vid not in found:
                found[vid] = q

    videos = []
    for ids in _chunks(found, 50):
        res = get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)})
        quota += 1
        for it in res.get("items", []):
            dur = iso_duration(it["contentDetails"].get("duration"))
            if dur == 0 or dur > max_duration:
                continue
            sn, st = it["snippet"], it.get("statistics", {})
            videos.append({
                "id": it["id"], "title": sn.get("title", ""), "description": sn.get("description", ""),
                "tags": sn.get("tags", []), "channel_id": sn.get("channelId"),
                "channel": sn.get("channelTitle", ""), "published": sn.get("publishedAt"),
                "views": int(st.get("viewCount", 0)), "likes": int(st.get("likeCount", 0)),
                "comments": int(st.get("commentCount", 0)), "duration": dur, "query": found[it["id"]],
                "url": f"https://www.youtube.com/shorts/{it['id']}",
            })

    subs = {}
    channel_ids = {v["channel_id"] for v in videos if v["channel_id"]}
    for ids in _chunks(channel_ids, 50):
        res = get("channels", {"part": "statistics", "id": ",".join(ids)})
        quota += 1
        for it in res.get("items", []):
            st = it.get("statistics", {})
            subs[it["id"]] = None if st.get("hiddenSubscriberCount") else int(st.get("subscriberCount", 0))
    for v in videos:
        v["subs"] = subs.get(v["channel_id"])
    return videos, quota
