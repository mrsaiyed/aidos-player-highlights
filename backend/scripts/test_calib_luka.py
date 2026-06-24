"""Track B generalization test: auto-calibrate the Luka (DAL@ATL) broadcast and visualize."""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2

from app.services.autocalibrate_service import auto_calibrate
from app.utils.ffmpeg import _resolve_tool

GAME = "0022300634"
V = os.path.join(os.path.dirname(__file__), "..", "data", "uploads", GAME, "full_game.mp4")
OUT = tempfile.gettempdir()

prof = auto_calibrate(V, GAME)
print("PROFILE:", prof)
if prof:
    ff = _resolve_tool("ffmpeg")
    frame = os.path.join(OUT, "luka_frame.jpg")
    subprocess.run([ff, "-ss", "2800", "-i", V, "-vframes", "1", "-q:v", "2", "-y", frame],
                   capture_output=True)
    img = cv2.imread(frame)
    if img is not None:
        vis = img.copy()
        for k, (x, y, w, h) in prof.items():
            cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.imwrite(os.path.join(OUT, f"luka_{k}.jpg"),
                        cv2.resize(img[y:y + h, x:x + w], None, fx=4, fy=4))
        cv2.imwrite(os.path.join(OUT, "luka_vis.jpg"), vis)
        print("wrote luka_vis.jpg and region crops to", OUT)
