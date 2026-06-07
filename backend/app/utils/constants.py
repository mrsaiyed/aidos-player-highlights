QUARTER_DURATION_SECONDS = 720
CLIP_PRE_ROLL_SECONDS = 5
CLIP_POST_ROLL_SECONDS = 3
CLIP_TOTAL_SECONDS = 8
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

# Phase 6: Clock OCR pipeline
CLOCK_OCR_SAMPLE_INTERVAL = 2.0        # extract one frame every N seconds
CLOCK_OCR_MIN_CONFIDENCE = 0.30        # discard OCR reads below this (0-1)
CLOCK_OCR_MAX_JUMP_FORWARD = 3.0       # max seconds clock can "increase" between frames (allows small OCR jitter)
CLOCK_OCR_MAX_JUMP_BACKWARD = 120.0    # max seconds clock can decrease between frames (allows timeouts)

# Phase 6: Event resolver confidence thresholds
RESOLVER_HIGH_CONFIDENCE_GAP = 5.0     # nearest clock reading within 5s of event = high
RESOLVER_MEDIUM_CONFIDENCE_GAP = 30.0  # nearest clock reading within 30s = medium; beyond = low
OCR_HIGH_CONFIDENCE_OFFSET = 3.0       # seconds to shift HIGH confidence timestamps forward (compensates for dead ball between reading and shot)
