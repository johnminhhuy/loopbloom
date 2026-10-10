# ShortsBot + TrendWatcher

Makes funny vertical Shorts automatically:

**funny clip -> melodica cover underneath -> meme image pops up with a "fahhh" at the funny moment -> loop or hard cut**

and (optionally) learns what's trending on YouTube Shorts each week, so song / sound-effect / length choices follow the trend. Everything uses free tools and free API tiers.

---

## 1. Setup (about 10 minutes)

1. **Python 3.10+** and **ffmpeg** (must be on PATH).
   - Windows: `winget install Gyan.FFmpeg`, then open a new terminal.
   - Mac: `brew install ffmpeg`. Linux: `sudo apt install ffmpeg`.
2. In this folder: `pip install -r requirements.txt`
3. `python run.py init` (creates folders + tiny placeholder assets)
4. `python run.py doctor` (tells you what's missing)

## 2. Add your assets (this is what makes the videos good)

| Folder | What to put in it | Where to get it |
|---|---|---|
| `assets/music/` | Melodica / voice covers (.mp3/.wav), **10-30 s each** | MyInstants "melodica" soundboard, or save sounds from TikTok/YouTube |
| `assets/sfx/` | `fahhh.mp3`, `vine_boom.mp3`, `oof.mp3`, `bruh.mp3` ... | MyInstants, fahhh.me |
| `assets/memes/` | Reaction images, **PNG with transparent background** | any meme image, cut out the background (remove.bg, Photopea) |

- **Name files after what they are** (`phoebe_melodica.mp3`, `let_me_know.mp3`, `fahhh.mp3`). TrendWatcher matches trending names to your filenames; that's how it knows which of your files to favour.
- Optional `assets/tags.json` so Gemini can pick fitting memes:
  `{"shocked_pikachu.png": ["shock", "surprise"], "crying_cat.png": ["cry", "sad"]}`

## 3. Make videos

```
python run.py make --clip some_video.mp4     # use a file you already have
python run.py make                           # fetch a clip from the configured source
python run.py make --source reddit --count 3
```

Finished videos land in `output/` (`short_*.mp4` plus a `.json` with title/description/credit).

**Clip sources** (set `source.mode` in `config.yaml`, or pass `--source`):
- `local`: drop videos in `inbox/`
- `reddit`: top posts of the subreddits in the config (downloaded with yt-dlp); credit is auto-written
- `youtube`: yt-dlp search of your queries; set `creative_commons_only: true` to restrict to CC-licensed videos

Used clips are remembered in `state.json` so nothing repeats.

## 4. Upload to YouTube (optional, free)

1. Go to <https://console.cloud.google.com>, create a project, **enable "YouTube Data API v3"**.
2. *APIs & Services -> OAuth consent screen*: set up, add **your own Google account as a test user**.
3. *Credentials -> Create credentials -> OAuth client ID -> Desktop app*. Download the JSON, save it here as `client_secret.json`.
4. `python run.py auth` (browser opens once; token saved to `token.json`). It also prints `YT_CLIENT_ID`, `YT_CLIENT_SECRET` and `YT_REFRESH_TOKEN`.
5. `python run.py make --upload` or `python run.py upload`.

**Headless uploads (like Loopbloom):** put those three values in `.env` (or as environment variables / GitHub Actions secrets). When all three are set, uploads use them directly: no `token.json`, no browser, no `client_secret.json` needed on the machine. Transient YouTube errors (500/502/503/504) and network drops are retried automatically.

For a long-lived refresh token, set the OAuth consent screen to **In production** (in *Testing* mode Google expires the token after ~7 days).

Limits to know: each upload costs 1,600 of the free 10,000 daily quota units (about **6 uploads/day**), and videos uploaded by an **unaudited** API project may be forced to **private** until Google audits it (the form is free, search "YouTube API Services audit").

## 5. TrendWatcher (optional, free)

Needs a **YouTube Data API key** (same Cloud project: *Credentials -> API key*) and, for the good version, a **Gemini API key** (<https://aistudio.google.com>, free). Copy `.env.example` to `.env` and paste them in.

```
python run.py trends
```

What it does: searches your trend queries -> ranks recent Shorts by *over-performance* (views vs. channel size, and views/hour) -> breaks the winners down (Gemini watches them and reports length, popup timing, sfx, song; without a Gemini key it falls back to titles/tags only) -> writes **`template.json`**.

ShortsBot reads `template.json` automatically: song/sfx are picked by trending weight (rising ones favoured, 20% random exploration), clip length follows the median, popup timing follows the median.

It also writes:
- `missing_assets.txt`: songs/sounds that are trending but not in your folders. **Go add them.**
- `reports/DATE.md`: readable summary + the top outlier videos to look at yourself.
- Newly spotted song names feed next week's search queries by themselves.

A search costs 100 quota units; the default 6-10 queries is a small slice of the daily 10,000. Gemini results are cached in `trend_cache/`, so no video is analysed twice.

## 6. Full autopilot

`python run.py daily --count 3 --upload` refreshes trends if the template is >7 days old, makes 3 videos, uploads them.

- **Windows**: Task Scheduler -> Create Basic Task -> daily -> Action "Start a program": `python`, arguments `run.py daily --count 3 --upload`, "Start in": this folder.
- **Mac/Linux**: `0 9 * * * cd /path/to/shortsbot && python3 run.py daily --count 3 --upload`

(Your PC must be on at that time.)

## The meme hit (flashbang)

The popup is a full-screen hit: white-out flash, the meme slams in zoomed 1.4x and snaps down, the screen shakes, then it hard-cuts back to the clip. The clip's audio and the music drop for ~0.6s so the sound effect lands harder. Transparent PNGs are placed on a blurred copy of themselves so the whole screen is always filled; normal photos/JPGs are cover-fitted.

Tune it in `config.yaml` under `video.popup`: `duration`, `flash`, `punch_scale`, `shake_px`, `duck`, or set `fullscreen: false` for the old centred card.

## Settings

Everything is in `config.yaml` (see `shortsbot/config.py` for all options): clip length limits, music/original/sfx volumes, popup size and duration, loop mode, subreddits, privacy.

Turn on smarter moment detection with `detect.use_gemini: true`. Default is a free local detector (loudness jumps + motion spikes).

---

## Honest status: what was tested

**Tested here (with synthetic clips):** the whole video path (moment detection, 9:16 reframing with blurred background, melodica bed, popup animation, sfx timing, looping, silent clips, vertical clips), asset picking with template weights, the trend scoring / song identification / aggregation (with mocked YouTube data), `doctor`, `init`.

**Written but NOT run (my sandbox has no internet):** the real calls to Reddit, yt-dlp, the YouTube Data API, Gemini, and the YouTube upload. They follow the official API shapes, but expect a bug or two on first contact. If something errors, paste the error message back and it's usually a one-line fix.

**Things that may need updating over time:** Gemini model names (`gemini.models` in config; it tries each in order), Reddit sometimes blocks unauthenticated requests (use `--source youtube` or `local` then).

**Limits of the design:**
- Trend data lags: by the time something shows in view counts it's already mid-peak.
- Gemini's timing/song identification is approximate; the weights average over many videos, so single mistakes wash out.
- It can tell you a song is trending, but can't create the audio file; that's what `missing_assets.txt` is for.
- Channels built purely from other people's clips with light edits risk Content ID claims, strikes, or YouTube's "reused content" demonetisation. Credit lines go in the description automatically but don't remove that risk.

## 7. Run in the cloud like Loopbloom (GitHub Actions, no PC needed)

`.github/workflows/daily.yml` runs `python run.py daily --count 1 --upload` 3 times a day (edit the cron line to change it; keep under ~6 uploads/day for the API quota).

1. Create a **public** GitHub repo (free runners) and push this folder. `assets/` must be committed (music, sfx, memes); `.env` is ignored, so your keys go in secrets.
2. Settings > Secrets and variables > Actions, add: `YT_CLIENT_ID`, `YT_CLIENT_SECRET`, `YT_REFRESH_TOKEN` (printed by `python run.py auth`), plus optional `GEMINI_API_KEY`, `YOUTUBE_API_KEY`, `DISCORD_WEBHOOK` (failure alerts), `YT_COOKIES`.
3. Actions tab > daily-shorts > Run workflow to test.

`state.json` is committed each run so used clips are never repeated and GitHub doesn't pause the schedule.

**Catch:** YouTube often blocks yt-dlp from GitHub's servers ("Sign in to confirm you're not a bot"). If that happens, export your YouTube cookies (browser extension "Get cookies.txt LOCALLY") into the `YT_COOKIES` secret; the bot then passes them to yt-dlp. Reddit can also block cloud IPs. A fully safe alternative is `source.mode: local` with clips committed to `inbox/`.

**Cookies as one line of text:** turn `cookies.txt` into a single string and save that as the secret `YT_COOKIES_B64`.
Windows (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cookies.txt")) | Set-Clipboard`
Mac/Linux: `base64 -w0 cookies.txt` (Mac: `base64 -i cookies.txt | tr -d '\n'`)
Then paste the clipboard/output into the secret. The workflow decodes it back into `cookies.txt`.
