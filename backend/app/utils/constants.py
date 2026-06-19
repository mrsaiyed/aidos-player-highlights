QUARTER_DURATION_SECONDS = 720
# Legacy fixed-window roll values (Phase 5A). Superseded by the net-relative dynamic
# window below; kept only for backward compatibility with older clip-bounds calls.
CLIP_PRE_ROLL_SECONDS = 5
CLIP_POST_ROLL_SECONDS = 3
CLIP_TOTAL_SECONDS = 8

# Phase 6 dynamic clip window (net-relative). The scorebug score flip trails the ball
# through the net by ~3s of broadcast delay (measured from v2 clip review: e.g. KCP 6:40
# net at 439s, scorebug flip at 442s). We anchor on (flip - lag) = the net moment so the
# ball lands CLIP_LEAD seconds into the clip.
SCORE_FLIP_LAG_SECONDS = 3.0   # seconds the scorebug flip trails the ball through the net
CLIP_LEAD_SECONDS = 5          # seconds before the net to start a clip
CLIP_TRAIL_SECONDS = 3         # seconds after the net to end a clip
TRANSITION_MAX_LEAD_SECONDS = 10  # cap on transition lead (detected + stored; not applied to bounds yet)
SHORT_MAX_DURATION_SECONDS = 120
MINIMUM_IMPORTANCE_SCORE = 70
FRAME_SAMPLE_INTERVAL_SECONDS = 30
NBA_QUARTERS = [1, 2, 3, 4]
OVERTIME_DURATION_SECONDS = 300

# Limits clips per player; raised to 20 for full-game reels
MAX_CLIPS_PER_PLAYER = 20

# Phase 5A: Self-correcting anchor chain constants
REFINEMENT_WINDOW_SECONDS = 45
QUARTER_BREAK_SEARCH_SECONDS = 300
DEGRADED_WINDOW_MULTIPLIER = 3
DEAD_BALL_RATIO = 1.6

# Phase 6 anchor chain uses forward score-signature scanning; the scan reach is configured
# by _SCAN_CHUNKS in score_change_detector.py (no fixed per-quarter window needed).

# Phase 6: Clock OCR pipeline
CLOCK_OCR_SAMPLE_INTERVAL = 2.0        # extract one frame every N seconds
CLOCK_OCR_MIN_CONFIDENCE = 0.30        # discard OCR reads below this (0-1)
CLOCK_OCR_MAX_JUMP_FORWARD = 3.0       # max seconds clock can "increase" between frames (allows small OCR jitter)
CLOCK_OCR_MAX_JUMP_BACKWARD = 120.0    # max seconds clock can decrease between frames (allows timeouts)

# Phase 6: Event resolver confidence thresholds
RESOLVER_HIGH_CONFIDENCE_GAP = 5.0     # nearest clock reading within 5s of event = high
RESOLVER_MEDIUM_CONFIDENCE_GAP = 30.0  # nearest clock reading within 30s = medium; beyond = low
# Score change detection (frame sampling + white-digit masking)
SCORE_VERIFY_FPS = 2                   # frames per second extracted in a scan window
SCORE_WHITE_THRESHOLD = 170           # BGR channel min for a "white digit" pixel
SCORE_CHANGE_PX = 70                   # frame-to-frame mask-diff pixel count to call a candidate change
