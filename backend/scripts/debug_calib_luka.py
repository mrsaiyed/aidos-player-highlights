"""Debug: dump what auto-calibrate's OCR sees on the Luka (DAL@ATL) broadcast."""
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2

from app.services.nba_service import NBAService
from app.services.score_change_detector import _get_reader
from app.utils.ffmpeg import _resolve_tool, get_video_duration

GAME = "0022300634"
V = os.path.join(os.path.dirname(__file__), "..", "data", "uploads", GAME, "full_game.mp4")
N = 28
GRID = 40
CLOCK_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def main():
    dur = get_video_duration(V)
    times = [dur * (0.04 + 0.89 * i / (N - 1)) for i in range(N)]
    home = away = 0
    for e in NBAService().fetch_play_by_play(GAME):
        sa = (e.get("score_after") or "").split()
        if len(sa) >= 4:
            try:
                home, away = int(sa[1]), int(sa[3])
            except ValueError:
                pass
    print(f"final home(ATL)={home} away(DAL)={away}\n")

    reader = _get_reader()
    ff = _resolve_tool("ffmpeg") or "ffmpeg"
    num = defaultdict(list)
    clk = defaultdict(list)
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = os.path.join(tmp, f"f{i}.jpg")
            subprocess.run([ff, "-ss", f"{t:.2f}", "-i", V, "-vframes", "1", "-q:v", "2", "-y", p],
                           capture_output=True)
            img = cv2.imread(p)
            if img is None:
                continue
            for box, text, _ in reader.readtext(img, allowlist="0123456789:"):
                xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
                x, y, w, h = min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
                cell = (int((x + w / 2) // GRID), int((y + h / 2) // GRID))
                if CLOCK_RE.match(text.strip()):
                    clk[cell].append((i, text.strip(), int(x), int(y)))
                else:
                    d = "".join(c for c in text if c.isdigit())
                    if d and int(d) <= 199:
                        num[cell].append((i, int(d), int(x), int(y)))

    print("Numeric regions (n>=6), sorted by max value:")
    rows = []
    for cell, obs in num.items():
        if len(obs) < 6:
            continue
        obs.sort()
        vals = [v for _, v, *_ in obs]
        nondec = sum(vals[k] <= vals[k + 1] for k in range(len(vals) - 1)) / max(1, len(vals) - 1)
        x = min(o[2] for o in obs); y = min(o[3] for o in obs)
        rows.append((max(vals), len(obs), nondec, x, y, vals))
    rows.sort(reverse=True)
    for mx, n, nd, x, y, vals in rows:
        print(f"  ({x:>4},{y:>4}) n={n:>2} nondec={nd:.2f} max={mx:>3} vals={vals[:3]}..{vals[-3:]}")

    print("\nClock (MM:SS) regions:")
    for cell, obs in clk.items():
        if len(obs) < 4:
            continue
        x = min(o[2] for o in obs); y = min(o[3] for o in obs)
        print(f"  ({x:>4},{y:>4}) n={len(obs):>2}  e.g. {[o[1] for o in obs[:5]]}")


if __name__ == "__main__":
    main()
