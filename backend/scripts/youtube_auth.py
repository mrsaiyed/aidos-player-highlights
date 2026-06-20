"""One-time YouTube connect (robust manual flow — no local server).

Run once: authorize in the browser, then paste back the URL your browser lands on. Saves a
refresh token so every future publish is silent.

    backend\\.venv\\Scripts\\python.exe backend\\scripts\\youtube_auth.py
"""

import os
import sys
import webbrowser

# The loopback redirect is http://localhost (not https); oauthlib blocks that by default.
# Safe for a localhost loopback exchange — allow it so the token swap succeeds.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from google_auth_oauthlib.flow import Flow

from app.services.youtube_publisher import CLIENT_FILE, TOKEN_FILE, SCOPES


def main():
    if not os.path.exists(CLIENT_FILE):
        print(f"OAuth client not found: {CLIENT_FILE}")
        sys.exit(1)

    # Manual loopback flow: the browser redirect lands on a localhost page that won't load,
    # but its address bar holds the ?code=... we need. Robust to firewalls/timeouts.
    flow = Flow.from_client_secrets_file(CLIENT_FILE, SCOPES, redirect_uri="http://localhost")
    auth_url, _ = flow.authorization_url(access_type="offline", prompt="consent",
                                         include_granted_scopes="true")

    print("\n=== Connect YouTube ===\n")
    print("1) Opening your browser to authorize (or copy the URL below).\n")
    print(auth_url + "\n")
    print("2) Pick the account, pass 'Google hasn't verified this app'")
    print("   (Advanced -> Go to <app> (unsafe)), then click Allow.")
    print("3) Your browser will try to open a 'localhost' page that FAILS to load — that's")
    print("   expected. Copy the FULL URL from the address bar (it contains '?code=').\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    resp = input("Paste that full redirected URL here:\n> ").strip()
    flow.fetch_token(authorization_response=resp)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(flow.credentials.to_json())
    print(f"\nConnected. Token saved to {TOKEN_FILE}")
    print("You can now run publish_reel.py — uploads will be silent from here on.")


if __name__ == "__main__":
    main()
