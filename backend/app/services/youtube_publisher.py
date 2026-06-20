"""YouTube publisher — upload a reel via the YouTube Data API.

One Publisher in front of the upload so other platforms can implement the same `publish()`
later. OAuth uses an installed-app (desktop) client: the first call opens a browser for consent
and caches a refresh token, so subsequent uploads are silent.

Files (gitignored, under backend/secrets/):
  youtube_client.json  — the OAuth client you downloaded from Google Cloud
  youtube_token.json   — saved access/refresh token (created on first auth)
"""

import logging
import os

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SECRETS = os.path.join(BACKEND, "secrets")
CLIENT_FILE = os.path.join(SECRETS, "youtube_client.json")
TOKEN_FILE = os.path.join(SECRETS, "youtube_token.json")

# Category 17 = "Sports" in the YouTube Data API.
SPORTS_CATEGORY_ID = "17"


def title_from_meta(meta: dict) -> str:
    """Build a human title from a compose metadata sidecar."""
    players = meta.get("players") or []
    opponents = meta.get("opponents") or []
    filters = meta.get("filters") or {}
    who = players[0] if len(players) == 1 else (filters.get("team") or "NBA")

    cat = filters.get("category") or filters.get("subtype")
    if not cat and filters.get("value"):
        cat = f"{filters['value']}-pointers"
    label = {"three": "3-Pointers", "two": "2-Pointers", "dunk": "Dunks", "layup": "Layups",
             "floater": "Floaters", "midrange": "Midrange", "paint": "Paint Buckets"}.get(
        str(cat).lower(), (str(cat).replace("_", " ").title() if cat else "Highlights"))

    vs = f" vs {opponents[0]}" if len(opponents) == 1 else ""
    when = ""
    if meta.get("date_min"):
        when = f" ({meta['date_min']})" if meta["date_min"] == meta.get("date_max") else f" ({meta['date_min']}…{meta['date_max']})"
    elif filters.get("season"):
        when = f" ({filters['season']})"
    return f"{who} — {label}{vs}{when}"


def description_from_meta(meta: dict) -> str:
    lines = [f"{meta.get('clip_count', 0)} clips.", ""]
    for c in meta.get("clips", []):
        lines.append(f"Q{c['period']} {c['clock']} — {c['player']} ({c.get('subtype') or 'shot'})")
    lines += ["", "Auto-generated from NBA play-by-play."]
    return "\n".join(lines)


class YouTubePublisher:
    def __init__(self, client_file: str = CLIENT_FILE, token_file: str = TOKEN_FILE):
        self.client_file = client_file
        self.token_file = token_file
        self._service = None

    def _credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(self.client_file):
                raise FileNotFoundError(f"OAuth client not found: {self.client_file}")
            flow = InstalledAppFlow.from_client_secrets_file(self.client_file, SCOPES)
            creds = flow.run_local_server(port=0)  # opens a browser for consent
        with open(self.token_file, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        return creds

    def service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            self._service = build("youtube", "v3", credentials=self._credentials())
        return self._service

    def publish(self, video_path: str, title: str, description: str = "",
                tags: list[str] | None = None, privacy: str = "private") -> dict:
        from googleapiclient.http import MediaFileUpload

        if not os.path.exists(video_path):
            raise FileNotFoundError(video_path)
        body = {
            "snippet": {"title": title[:100], "description": description,
                        "tags": tags or [], "categoryId": SPORTS_CATEGORY_ID},
            "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        req = self.service().videos().insert(part="snippet,status", body=body, media_body=media)

        logger.info("Uploading %s as '%s' (%s)", os.path.basename(video_path), title, privacy)
        resp = None
        while resp is None:
            status, resp = req.next_chunk()
            if status:
                logger.info("  %d%%", int(status.progress() * 100))
        vid = resp["id"]
        return {"video_id": vid, "url": f"https://youtu.be/{vid}", "title": title, "privacy": privacy}
