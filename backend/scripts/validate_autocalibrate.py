"""End-to-end check: auto-calibrate the ESPN game, then run the detector with the DISCOVERED
profile and confirm it finds the same play timestamps as the hardcoded `espn` profile.

    .venv/Scripts/python.exe scripts/validate_autocalibrate.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.autocalibrate_service import auto_calibrate
from app.services.score_change_detector import find_score_transition
from app.utils.scorebug_regions import register_profile, get_profile

GAME_ID = "0052000121"
BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
VIDEO = os.path.join(BACKEND, "data", "uploads", GAME_ID, "full_game.mp4")

# (name, search_from, score_before, score_after, ground-truth second)
CASES = [
    ("Drummond", 28, "LAL 0 GSW 2", "LAL 2 GSW 2", 82),
    ("James", 82, "LAL 2 GSW 9", "LAL 4 GSW 9", 258),
    ("KCP 6:40", 258, "LAL 4 GSW 15", "LAL 7 GSW 15", 442),
    ("KCP 4:43", 442, "LAL 10 GSW 17", "LAL 13 GSW 17", 687),
    ("Caruso 4:13", 687, "LAL 13 GSW 17", "LAL 16 GSW 17", 752),
]


def main():
    print("Auto-calibrating ESPN game...")
    prof = auto_calibrate(VIDEO, GAME_ID)
    if not prof:
        print("Calibration FAILED."); return
    register_profile("espn_auto", prof)
    print(f"\nDiscovered profile: {prof}")
    print(f"Hardcoded espn:     {{k: get_profile('espn')[k] for k in prof}}\n".replace(
        "{k: get_profile('espn')[k] for k in prof}",
        str({k: get_profile("espn")[k] for k in prof})))

    print("Detector run with the AUTO profile:")
    ok = 0
    for name, frm, before, after, gt in CASES:
        r = find_score_transition(VIDEO, frm, before, after, "espn_auto")
        if r.verified:
            d = r.video_second - gt
            ok += abs(d) <= 2.0
            print(f"  {name:<12} det={r.video_second:7.1f}  gt={gt}  delta={d:+.1f}")
        else:
            print(f"  {name:<12} NOT FOUND (gt={gt})")
    print(f"\nwithin +-2s of ground truth: {ok}/{len(CASES)}  (auto profile drives the detector correctly if ~5/5)")


if __name__ == "__main__":
    main()
