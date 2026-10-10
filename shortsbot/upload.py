"""YouTube upload through the Data API v3 (OAuth, resumable, retrying).

Credentials, in order of preference (same scheme as Loopbloom):
  1. env vars YT_CLIENT_ID + YT_CLIENT_SECRET + YT_REFRESH_TOKEN  (headless: servers, GitHub Actions, cron)
  2. token.json from `python run.py auth` (browser login, refreshed automatically)
"""
import json
import os
import time
from pathlib import Path

from .util import ROOT, log

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_URI = "https://oauth2.googleapis.com/token"
ENV_KEYS = ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")


def have_env_credentials():
    return all(os.environ.get(k) for k in ENV_KEYS)


def credentials(cfg):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if have_env_credentials():
        creds = Credentials(
            None,
            refresh_token=os.environ["YT_REFRESH_TOKEN"],
            token_uri=TOKEN_URI,
            client_id=os.environ["YT_CLIENT_ID"],
            client_secret=os.environ["YT_CLIENT_SECRET"],
            scopes=SCOPES,
        )
        creds.refresh(Request())
        return creds

    from google_auth_oauthlib.flow import InstalledAppFlow

    tok = ROOT / cfg["upload"]["token"]
    sec = ROOT / cfg["upload"]["client_secret"]
    creds = None
    if tok.exists():
        creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not sec.exists():
            raise RuntimeError(
                f"{sec.name} not found and YT_* env vars not set. See README 'Upload to YouTube'.")
        flow = InstalledAppFlow.from_client_secrets_file(str(sec), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    tok.write_text(creds.to_json(), encoding="utf-8")
    return creds


def print_secrets(creds):
    """Print the three values to paste into env / GitHub secrets for headless uploads."""
    print("\nFor headless uploads (server, GitHub Actions) set these three:")
    print("YT_CLIENT_ID     =", creds.client_id)
    print("YT_CLIENT_SECRET =", creds.client_secret)
    print("YT_REFRESH_TOKEN =", creds.refresh_token)


def upload(path, meta, cfg):
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    yt = build("youtube", "v3", credentials=credentials(cfg), cache_discovery=False)
    body = {
        "snippet": {"title": meta["title"][:100], "description": meta["description"],
                    "tags": meta.get("tags", []), "categoryId": str(cfg["upload"]["category_id"])},
        "status": {"privacyStatus": cfg["upload"]["privacy"], "selfDeclaredMadeForKids": False},
    }
    media = MediaFileUpload(str(path), mimetype="video/mp4", chunksize=-1, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp, tries = None, 0
    while resp is None:
        try:
            _, resp = req.next_chunk()
        except HttpError as e:
            if e.resp.status in (500, 502, 503, 504) and tries < 5:
                tries += 1
                log(f"upload hiccup ({e.resp.status}), retry {tries}/5")
                time.sleep(2 ** tries)
                continue
            raise
        except (ConnectionError, TimeoutError, OSError) as e:
            if tries < 5:
                tries += 1
                log(f"upload network error ({e}), retry {tries}/5")
                time.sleep(2 ** tries)
                continue
            raise
    log(f"uploaded: https://youtube.com/shorts/{resp['id']}")
    return resp["id"]
