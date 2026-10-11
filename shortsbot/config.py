"""Config loading: built-in defaults, overridden by config.yaml."""
import copy
from pathlib import Path

import yaml
from .util import ROOT

DEFAULTS = {
    "source": {
        "mode": "local",              # local | reddit | youtube
        "min_seconds": 4,
        "max_seconds": 60,
        # titles containing any of these words are skipped before download. Empty = skip nothing.
        # example: ["compilation", "sponsored"]
        "skip_words": [],
        "reddit": {
            "subreddits": ["funny", "Unexpected", "instant_regret", "nonononoyes", "holdmybeer", "AnimalsBeingDerps"],
            "time": "week",           # hour | day | week | month | year | all
            "limit": 50,
        },
        "youtube": {
            "queries": ["funny fail", "funny animals", "unexpected moment"],
            "search_n": 25,
            "creative_commons_only": False,
        },
    },
    "video": {
        "width": 1080, "height": 1920, "fps": 30,
        "min_len": 6, "max_len": 60, "default_len": 15,
        "original_volume": 0.45,       # volume of the clip's own audio
        "mute_original": False,
        "music_volume": 0.55,
        "sfx_volume": 1.0,
        "loop": "auto",                # auto | always | never
        "loop_if_shorter_than": 8,     # auto mode loops clips shorter than this (seconds)
        "popup": {
            "fullscreen": True,        # meme covers the whole screen (False = centred card, see width_frac)
            "fit": "auto",             # auto | contain | cover.  contain = whole meme visible on a blurred backdrop,
                                       # cover = crop to fill the screen, auto = cover only if already phone-shaped
            "duration": 1.0,           # seconds on screen, then a hard cut back to the clip
            "flash": True,             # white-out flashbang at the start
            "flash_hold_frames": 2,    # frames of pure white before it decays
            "punch_scale": 1.4,        # starts this zoomed-in, snaps down to 1.0
            "shake_px": 30,            # screen-shake amplitude (decays quickly)
            "duck": 0.2,               # music + clip audio drop to this level under the hit (1 = no ducking)
            "duck_len": 0.6,           # seconds of ducking
            "width_frac": 0.78,        # only used when fullscreen is False
            "y_frac": 0.5,
        },
    },
    "detect": {
        "use_gemini": False,           # ask Gemini for the funny moment (needs GEMINI_API_KEY)
        "min_t": 1.0,
        "audio_weight": 0.6,
        "motion_weight": 0.4,
    },
    "gemini": {
        # tried in order; first that works wins. Update if Google renames models.
        "models": ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-flash-latest"],
        "timeout": 120,
        "delay_between_calls": 6,
    },
    "assets": {"avoid_repeat_last": 8},
    "upload": {
        "privacy": "public",
        "category_id": "23",           # 23 = Comedy
        "client_secret": "client_secret.json",
        "token": "token.json",
        "default_tags": ["funny", "shorts", "meme", "melodica"],
    },
    "metadata": {
        "titles": [
            "wait for it 💀", "I can't stop watching this 😭", "the melodica knew 💀",
            "nobody was ready for that", "this is so unfair 😂", "bro really did that 💀",
            "the way this ends 😭", "perfect timing 💀",
        ],
        "hashtags": ["#shorts", "#funny", "#meme", "#melodica"],
    },
    "trend": {
        "queries": ["melodica meme", "melodica cover meme", "fahhh meme", "funny meme edit shorts",
                    "meme sound effect shorts", "accuracy meme shorts"],
        "extra_queries_limit": 4,
        "days_back": 14,
        "per_query": 25,
        "max_searches": 15,            # each search costs 100 quota units of the free 10,000/day
        "max_duration": 60,
        "analyze_top": 30,
        "keep_top": 40,
        "stale_after_days": 7,
        "exploration_rate": 0.2,
        "min_weight_for_missing": 0.05,
        "track_google_trends": True,
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path=None):
    p = Path(path) if path else ROOT / "config.yaml"
    user = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
    return _merge(DEFAULTS, user)
