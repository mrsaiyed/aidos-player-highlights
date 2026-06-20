"""Publish a composed reel to YouTube.

Reads data/outputs/composed/{name}/{name}.mp4 and its {name}.json metadata sidecar, builds a
title/description, and uploads. Running this IS the approval step — review the reel first.

    # preview the title/description without uploading:
    .venv/Scripts/python.exe scripts/publish_reel.py --name ad_dunks --dry-run
    # real upload (opens a browser for consent the first time):
    .venv/Scripts/python.exe scripts/publish_reel.py --name ad_dunks --privacy unlisted
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:  # keep unicode titles (em-dash) from crashing the Windows console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.services.youtube_publisher import YouTubePublisher, title_from_meta, description_from_meta

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPOSED_DIR = os.path.join(BACKEND, "data", "outputs", "composed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="composed reel name (folder under composed/)")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--title", help="override the auto-generated title")
    ap.add_argument("--tags", help="comma-separated tags")
    ap.add_argument("--dry-run", action="store_true", help="show what would upload, don't upload")
    args = ap.parse_args()

    folder = os.path.join(COMPOSED_DIR, args.name)
    reel = os.path.join(folder, f"{args.name}.mp4")
    meta_path = os.path.join(folder, f"{args.name}.json")
    if not os.path.exists(reel):
        print(f"Reel not found: {reel}  (run compose_reel first)"); return
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {"name": args.name}

    title = args.title or title_from_meta(meta)
    description = description_from_meta(meta)
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else (meta.get("players") or [])

    print(f"Reel:     {reel}")
    print(f"Title:    {title}")
    print(f"Privacy:  {args.privacy}")
    print(f"Tags:     {tags}")
    print(f"--- description ---\n{description}\n------------------")

    if args.dry_run:
        print("\n[dry-run] not uploading."); return

    res = YouTubePublisher().publish(reel, title, description, tags, args.privacy)
    print(f"\nUploaded: {res['url']}  ({res['privacy']})")


if __name__ == "__main__":
    main()
