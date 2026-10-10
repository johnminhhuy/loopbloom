"""Title / description / tags with credit lines."""
import random


def build(clip, music, sfx, gem, cfg):
    mcfg = cfg["metadata"]
    title = (gem or {}).get("title") or random.choice(mcfg["titles"])
    title = title.strip()
    if "#shorts" not in title.lower():
        title = f"{title} #shorts"
    title = title[:95]
    lines = []
    if clip.credit:
        lines.append(f"Original video: {clip.credit}")
        lines.append("All credit to the original creator. Contact me for removal.")
    if music:
        lines.append(f"Music: {music.stem.replace('_', ' ')}")
    if sfx:
        lines.append(f"Sound effect: {sfx.stem.replace('_', ' ')}")
    lines.append("")
    lines.append(" ".join(mcfg["hashtags"]))
    return {"title": title, "description": "\n".join(lines),
            "tags": list(cfg["upload"]["default_tags"])}
