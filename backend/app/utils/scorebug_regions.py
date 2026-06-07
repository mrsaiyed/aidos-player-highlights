"""Scorebug region configs per broadcast network.

Each config defines where the clock digits appear in a 1920x1080 frame.
Coordinates are (x, y, width, height) in pixels.

To add a new network: capture a frame, identify the clock region bounding box,
and add an entry here.
"""

PROFILES = {
    # ESPN broadcast — Play-In game 0052000121 (GSW vs LAL, May 19 2021)
    # Scorebug is a bottom bar across the full width; 1280x720 source.
    # Measured precisely from frame at t=60s (scorebug_bar.jpg).
    # Bar layout: [GS logo/score] [LAL logo/score] | [11:30 clock] [18 1st] | [StateFarm PLAY-IN] [ESPN]
    # "11:30" white digits are in upper half of bar, starting at x≈515
    # "1st" period text is in lower half of bar at x≈560
    "espn": {
        "scorebug_region": (0, 628, 1280, 92),   # full bottom bar
        "clock_region": (598, 636, 125, 32),      # MM:SS digits — wide enough for 1-digit minutes ("9:50") through "11:59"
        "period_region": (682, 668, 55, 28),      # quarter indicator ("1st" / "2nd" etc.)
    },
    # TNT broadcast — different games; scorebug top-left
    "tnt": {
        "scorebug_region": (0, 0, 420, 90),
        "clock_region": (135, 18, 140, 55),
        "period_region": (60, 18, 60, 55),
    },
    # ABC broadcast (same layout as ESPN)
    "abc": {
        "scorebug_region": (0, 630, 1280, 90),
        "clock_region": (740, 638, 150, 52),
        "period_region": (895, 638, 80, 52),
    },
}

DEFAULT_PROFILE = "espn"


def get_profile(name: str | None = None) -> dict:
    """Return the scorebug region profile by name, falling back to default."""
    return PROFILES.get(name or DEFAULT_PROFILE, PROFILES[DEFAULT_PROFILE])
