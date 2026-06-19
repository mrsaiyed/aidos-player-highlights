from unittest.mock import MagicMock, patch

import pytest

from app.services.refinement_service import RefinementService, Q1_TIP_OFF_SECOND
from app.services.score_change_detector import VerificationResult


def _make_moment(player, period, clock, score_before="LAL 0 GSW 0", score_after="LAL 2 GSW 0"):
    m = MagicMock()
    m.player_name = player
    m.period = period
    m.game_clock = clock
    m.description = f"{player} made shot"
    m.score_before = score_before
    m.score_after = score_after
    m.event_type = "made_shot"
    m.event_subtype = "jump_shot"
    m.video_time_seconds = None
    m.refinement_method = None
    m.confidence = None
    m.status = "pending"
    return m


@pytest.fixture
def service():
    return RefinementService()


@pytest.fixture
def mock_db():
    return MagicMock()


def _vr(verified, second, conf="high"):
    return VerificationResult(verified, second, conf, "score_change" if verified else "fallback")


# --- helpers still in use ---

def test_parse_clock_standard(service):
    assert service._parse_game_clock("11:10") == pytest.approx(670.0)


def test_parse_clock_bad_format(service):
    assert service._parse_game_clock("bad") == 0.0


def test_seconds_to_mmss(service):
    assert service._seconds_to_mmss(90.0) == "1:30"
    assert service._seconds_to_mmss(-5.0) == "0:00"


# --- forward-scan anchor chain ---

def test_confirmed_play_sets_high_confidence(service, mock_db):
    moment = _make_moment("Drummond", 1, "11:10", "LAL 0 GSW 2", "LAL 2 GSW 2")
    with patch("app.services.refinement_service.find_score_transition", return_value=_vr(True, 82.0)), \
         patch("os.path.exists", return_value=True):
        result = service.refine_moments(1, "0052000121", [moment], mock_db)

    assert moment.video_time_seconds == 82.0
    assert moment.confidence == "high"
    assert moment.refinement_method == "score_change"
    assert moment.status == "refined"
    assert result == {"total": 1, "confirmed": 1, "flagged": 0}


def test_anchor_advances_to_confirmed_second(service, mock_db):
    """Each play scans forward from the previous confirmed second."""
    m1 = _make_moment("Drummond", 1, "11:10", "LAL 0 GSW 2", "LAL 2 GSW 2")
    m2 = _make_moment("James", 1, "8:29", "LAL 2 GSW 9", "LAL 4 GSW 9")
    seen = []

    def fake(video, search_from, *a, **k):
        seen.append(search_from)
        return _vr(True, 82.0 if not seen[:-1] else 258.0)

    with patch("app.services.refinement_service.find_score_transition", side_effect=fake), \
         patch("os.path.exists", return_value=True):
        service.refine_moments(1, "0052000121", [m1, m2], mock_db)

    assert seen[0] == Q1_TIP_OFF_SECOND       # first play scans from tip-off
    assert seen[1] == 82.0                     # second play scans from m1's confirmed second


def test_missed_play_does_not_advance_anchor(service, mock_db):
    """A flagged play leaves the anchor put so the next play scans from the last good one."""
    m1 = _make_moment("Drummond", 1, "11:10", "LAL 0 GSW 2", "LAL 2 GSW 2")
    m2 = _make_moment("Ghost", 1, "9:00", "LAL 2 GSW 5", "LAL 4 GSW 5")  # missed
    m3 = _make_moment("James", 1, "8:29", "LAL 4 GSW 9", "LAL 6 GSW 9")
    seen = []

    def fake(video, search_from, before, after, *a, **k):
        seen.append(search_from)
        # m1 confirmed @82, m2 (LAL 2 GSW 5) missed, m3 confirmed @258
        if before == "LAL 0 GSW 2":
            return _vr(True, 82.0)
        if before == "LAL 2 GSW 5":
            return _vr(False, 0.0, "low")
        return _vr(True, 258.0)

    with patch("app.services.refinement_service.find_score_transition", side_effect=fake), \
         patch("os.path.exists", return_value=True):
        result = service.refine_moments(1, "0052000121", [m1, m2, m3], mock_db)

    assert m2.confidence == "low"
    assert m2.video_time_seconds is None
    assert m2.status == "unconfirmed"
    # m3 scanned from m1's 82 (m2's miss did not move the anchor)
    assert seen[2] == 82.0
    assert m3.video_time_seconds == 258.0
    assert result == {"total": 3, "confirmed": 2, "flagged": 1}


def test_watch_fallback_recovers_flagged_play(service, mock_db):
    moment = _make_moment("Caruso", 1, "4:13", "LAL 13 GSW 17", "LAL 16 GSW 17")
    with patch("app.services.refinement_service.find_score_transition", return_value=_vr(False, 0.0, "low")), \
         patch.object(service, "_run_watch_scan", return_value=752.0), \
         patch("os.path.exists", return_value=True):
        result = service.refine_moments(1, "0052000121", [moment], mock_db, use_watch_fallback=True)

    assert moment.video_time_seconds == 752.0
    assert moment.refinement_method == "watch_confirmed"
    assert moment.confidence == "high"
    assert result["confirmed"] == 1
