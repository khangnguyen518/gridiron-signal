"""Discord messages for scheduled runs: failures, and the pre-game lineup post.

The webhook URL comes from NFLM_ALERT_WEBHOOK_URL, or from the Secret Manager
secret version in NFLM_ALERT_SECRET (for example
projects/sports-db-209650/secrets/alert-discord-webhook/versions/latest), read
with Application Default Credentials. With neither set, messages only print.
"""

import base64

import google.auth
import requests
from google.auth.transport.requests import AuthorizedSession

from nfl_model import config

DISCORD_LIMIT = 1900  # Discord rejects messages over 2000 characters


def _webhook_url() -> str | None:
    if config.NFLM_ALERT_WEBHOOK_URL:
        return config.NFLM_ALERT_WEBHOOK_URL
    if not config.NFLM_ALERT_SECRET:
        return None
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    resp = AuthorizedSession(creds).get(
        f"https://secretmanager.googleapis.com/v1/{config.NFLM_ALERT_SECRET}:access", timeout=30
    )
    resp.raise_for_status()
    return base64.b64decode(resp.json()["payload"]["data"]).decode().strip() or None


def send(text: str) -> bool:
    """Posts text to Discord in chunks. Returns False when no webhook is configured
    or the post fails; a scheduled run must not crash because Discord is down."""
    print(text)
    try:
        url = _webhook_url()
    except (requests.RequestException, google.auth.exceptions.GoogleAuthError, KeyError) as exc:
        print(f"Alert webhook unavailable: {exc}")
        return False
    if not url:
        return False
    lines, chunk, ok = text.splitlines(), "", True
    for line in lines + [None]:
        if line is None or len(chunk) + len(line) + 1 > DISCORD_LIMIT:
            if chunk:
                try:
                    requests.post(url, json={"content": chunk}, timeout=30).raise_for_status()
                except requests.RequestException as exc:
                    print(f"Discord post failed: {exc}")
                    ok = False
            chunk = ""
        if line is not None:
            chunk += line + "\n"
    return ok
