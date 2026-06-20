"""Batch-publish every composed reel matching a prefix.

Per reel: if its duration is < --short-under seconds, publish as a Short (tags #Shorts);
otherwise as a regular video. Quota errors are caught per reel so one failure doesn't stop the
rest. NOTE: YouTube only classifies vertical/square videos as Shorts — landscape reels tagged
#Shorts will usually still appear as regular videos.

    .venv/Scripts/python.exe scripts/publish_player_reels.py --prefix lakers_buckets --short-under 90 --privacy unlisted
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app.services.youtube_publisher import YouTubePublisher, title_from_meta, description_from_meta
from app.utils.ffmpeg import get_video_duration

BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMPOSED_DIR = os.path.join(BACKEND, "data", "outputs", "composed")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", required=True, help="publish every composed reel named {prefix}_*")
    ap.add_argument("--short-under", type=float, default=90.0, dest="short_under",
                    help="reels shorter than this (s) are published as Shorts")
    ap.add_argument("--privacy", default="unlisted", choices=["private", "unlisted", "public"])
    args = ap.parse_args()

    names = sorted(
        d for d in os.listdir(COMPOSED_DIR)
        if d.startswith(args.prefix + "_") and os.path.isdir(os.path.join(COMPOSED_DIR, d))
        and os.path.exists(os.path.join(COMPOSED_DIR, d, f"{d}.mp4"))
    )
    if not names:
        print(f"No reels found matching {args.prefix}_*"); return
    print(f"Found {len(names)} reels for prefix '{args.prefix}'.\n")

    pub = YouTubePublisher()
    results = []
    for name in names:
        folder = os.path.join(COMPOSED_DIR, name)
        reel = os.path.join(folder, f"{name}.mp4")
        meta_path = os.path.join(folder, f"{name}.json")
        meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else {"name": name}

        dur = get_video_duration(reel)
        is_short = dur < args.short_under
        title = title_from_meta(meta)
        description = description_from_meta(meta)
        tags = (meta.get("players") or []) + (["Shorts"] if is_short else [])
        if is_short:
            title = (title + " #Shorts")[:100]
            description += "\n\n#Shorts"

        kind = "SHORT" if is_short else "video"
        print(f"-> {name}  {dur:.0f}s  [{kind}]  '{title}'", flush=True)
        try:
            res = pub.publish(reel, title, description, tags, args.privacy)
            results.append((name, kind, dur, res["url"]))
            print(f"   uploaded: {res['url']}")
        except Exception as exc:  # noqa: BLE001
            results.append((name, kind, dur, f"FAILED: {exc}"))
            print(f"   FAILED: {exc}")

    print("\n=== summary ===")
    for name, kind, dur, outcome in results:
        print(f"  {name:<32} {dur:>4.0f}s {kind:<6} {outcome}")


if __name__ == "__main__":
    main()
