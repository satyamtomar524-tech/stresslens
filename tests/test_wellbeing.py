"""Fictional work-session and in-app reminder behavior; no devices or sleeps."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from stresslens.session_report import SelfReport
from stresslens.wellbeing import WorkSession, checkin_record


@pytest.fixture
def work():
    clock = SimpleNamespace(value=0.0)
    anchor = datetime(2026, 10, 18, 9, tzinfo=UTC)
    session = WorkSession(clock=lambda: clock.value, utc_clock=lambda: anchor + timedelta(seconds=clock.value))
    return session, clock


def test_explicit_work_clock_pauses_resumes_and_ends_without_camera(work):
    session, clock = work
    assert session.state == "idle" and session.session_id is None and session.elapsed_seconds == 0
    assert not session.reminders_enabled and session.due_prompt() is None
    assert session.start()
    first_id = session.session_id
    clock.value = 90
    assert not session.start() and session.session_id == first_id
    assert session.pause() and session.elapsed_seconds == 90
    clock.value = 900
    assert session.elapsed_seconds == 90 and not session.pause()
    assert session.resume()
    clock.value = 920
    assert session.end() and session.elapsed_seconds == 110
    clock.value = 2000
    assert session.elapsed_seconds == 110 and not session.end() and not session.resume()
    assert session.start() and session.session_id != first_id and session.elapsed_seconds == 0


def test_long_return_produces_one_stable_due_prompt_and_no_catchup_storm(work):
    session, clock = work
    session.configure_reminders(True, 1800)
    session.start()
    clock.value = 18000
    prompt = session.due_prompt()
    assert prompt is not None
    assert all(session.due_prompt() is prompt for _ in range(20))
    assert session.answer_reminder(prompt.prompt_id, "dismiss")
    assert not session.answer_reminder(prompt.prompt_id, "dismiss")
    assert session.due_prompt() is None
    clock.value += 1799
    assert session.due_prompt() is None
    clock.value += 1
    assert session.due_prompt().prompt_id != prompt.prompt_id


def test_snooze_uses_active_work_time_and_take_break_pauses(work):
    session, clock = work
    session.configure_reminders(True, 60)
    session.start()
    clock.value = 60
    first = session.due_prompt()
    assert session.answer_reminder(first.prompt_id, "snooze")
    clock.value = 359
    assert session.due_prompt() is None
    clock.value = 360
    second = session.due_prompt()
    assert session.answer_reminder(second.prompt_id, "take_break")
    assert session.state == "paused" and session.elapsed_seconds == 360
    clock.value = 9000
    assert session.due_prompt() is None and session.elapsed_seconds == 360
    assert session.resume()
    clock.value += 59
    assert session.due_prompt() is None
    clock.value += 1
    assert session.due_prompt() is not None


def test_disabling_or_ending_cancels_pending_reminders(work):
    session, clock = work
    session.configure_reminders(True, 60)
    session.start()
    clock.value = 60
    prompt = session.due_prompt()
    session.configure_reminders(False, 60)
    assert session.due_prompt() is None
    assert not session.answer_reminder(prompt.prompt_id, "take_break")
    session.configure_reminders(True, 60)
    clock.value = 120
    assert session.due_prompt()
    session.end()
    assert session.due_prompt() is None


@pytest.mark.parametrize("interval", [0, 59, 10801, True, 30.5])
def test_invalid_reminder_interval_cannot_change_existing_configuration(work, interval):
    session, _ = work
    with pytest.raises(ValueError):
        session.configure_reminders(True, interval)
    assert not session.reminders_enabled and session.reminder_interval_seconds == 1800


@pytest.mark.parametrize("state,value", [("answered", 0), ("answered", 2), ("unsure", None), ("skipped", None)])
def test_point_adapter_preserves_existing_self_report_semantics(state, value):
    point = SelfReport("fictional-point", datetime(2026, 10, 18, 9, tzinfo=UTC), state, value)
    record = checkin_record(point, session_id="fictional-work", clarity="skipped")
    assert record == {"id": "fictional-point", "answered_at": "2026-10-18T09:00:00+00:00",
                      "session_id": "fictional-work", "stress_state": state, "stress_value": value,
                      "clarity": "skipped"}
    assert not any(key in record for key in ("camera", "text", "measurements", "score"))


def test_fresh_work_controller_does_not_restore_running_time_or_reminder_choice():
    restored = WorkSession()
    assert restored.state == "idle" and restored.session_id is None
    assert not restored.reminders_enabled and restored.elapsed_seconds == 0
