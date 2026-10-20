"""State/freshness presentation cannot make old measurements current."""
import pytest

from stresslens.live_status import live_status


def measured(**overrides):
    return {"status": "ok", "groups": {"Eye narrowing": 0.6}, "frame_age_seconds": 0.1, **overrides}


@pytest.mark.parametrize("age,current", [(0, True), (2, True), (2.001, False)])
def test_freshness_boundary_uses_existing_two_second_limit(age, current):
    status = live_status(measured(frame_age_seconds=age), running=True, stopping=False,
                         released=False, consented=True)
    assert status.current is current
    if not current:
        assert "stale" in status.message and "No usable" in status.title


@pytest.mark.parametrize("age", [None, -1, float("nan"), float("inf"), True])
def test_unknown_or_invalid_frame_age_cannot_support_current_coefficients(age):
    status = live_status(measured(frame_age_seconds=age), running=True, stopping=False,
                         released=False, consented=True)
    assert not status.current and status.state == "unavailable"
    assert status.freshness == "Frame freshness is unavailable."


@pytest.mark.parametrize("running,stopping,released,consented,state", [
    (False, False, True, True, "off"),
    (False, False, True, False, "off"),
    (False, False, False, True, "stopping"),
    (True, True, False, True, "stopping"),
    (True, False, False, False, "stopping"),
])
def test_lifecycle_and_consent_take_priority_over_old_valid_values(running, stopping, released, consented, state):
    status = live_status(measured(), running=running, stopping=stopping, released=released, consented=consented)
    assert status.state == state and not status.current
    assert not status.freshness


def test_new_frame_does_not_make_missing_face_usable():
    status = live_status(measured(status="no_face", message="No face detected"), running=True,
                         stopping=False, released=False, consented=True)
    assert not status.current and status.state == "unavailable"
    assert status.message == "No face detected"


def test_fresh_frame_without_coefficients_does_not_blame_frame_freshness():
    status = live_status(measured(groups={}), running=True, stopping=False, released=False, consented=True)
    assert not status.current and status.state == "unavailable"
    assert "coefficients" in status.message
    assert "Last frame received 0.1 seconds ago" in status.freshness


def test_failed_capture_after_release_stays_off_and_allows_a_deliberate_retry():
    status = live_status(measured(), running=False, stopping=False, released=True, consented=True,
                         error="Synthetic capture error", last_reason="capture_error")
    assert status.state == "off" and not status.current
    assert "previous capture failed" in status.message
    assert "Press Start camera" in status.message
