"""Camera-independent work clock and voluntary check-in adapter."""
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4


CLARITY_VALUES = frozenset({"clear", "mixed", "foggy", "unsure", "skipped"})


def utc_now():
    return datetime.now(UTC)


@dataclass(frozen=True)
class BreakPrompt:
    prompt_id: str
    session_id: str


class WorkSession:
    """Active work time only; a new controller always starts idle."""

    def __init__(self, clock=monotonic, utc_clock=utc_now):
        self.clock, self.utc_clock = clock, utc_clock
        self.state = "idle"
        self.session_id = None
        self.started_at = self.ended_at = None
        self._active_since = None
        self._elapsed = 0.0
        self.reminders_enabled = False
        self.reminder_interval_seconds = 1800
        self._next_due = None
        self._prompt = None

    @property
    def elapsed_seconds(self):
        extra = max(0.0, self.clock() - self._active_since) if self._active_since is not None else 0.0
        return self._elapsed + extra

    def start(self):
        if self.state in {"working", "paused"}:
            return False
        self.session_id = str(uuid4())
        self.started_at, self.ended_at = self.utc_clock(), None
        self._elapsed, self._active_since = 0.0, self.clock()
        self.state, self._prompt = "working", None
        self._next_due = self.reminder_interval_seconds if self.reminders_enabled else None
        return True

    def pause(self):
        if self.state != "working":
            return False
        self._elapsed = self.elapsed_seconds
        self._active_since, self._prompt, self.state = None, None, "paused"
        self._next_due = self._elapsed + self.reminder_interval_seconds if self.reminders_enabled else None
        return True

    def resume(self):
        if self.state != "paused":
            return False
        self._active_since, self.state = self.clock(), "working"
        return True

    def end(self):
        if self.state not in {"working", "paused"}:
            return False
        self._elapsed = self.elapsed_seconds
        self._active_since, self._next_due, self._prompt = None, None, None
        self.ended_at, self.state = self.utc_clock(), "ended"
        return True

    def configure_reminders(self, enabled, interval_seconds=1800):
        if type(enabled) is not bool or type(interval_seconds) is not int or not 60 <= interval_seconds <= 10800:
            raise ValueError("Choose a reminder interval from 1 to 180 whole minutes.")
        if (enabled, interval_seconds) == (self.reminders_enabled, self.reminder_interval_seconds):
            return False
        self.reminders_enabled, self.reminder_interval_seconds = enabled, interval_seconds
        self._prompt = None
        self._next_due = self.elapsed_seconds + interval_seconds if enabled else None
        return True

    def due_prompt(self):
        if self.state != "working" or not self.reminders_enabled:
            return None
        if self._prompt is None and self._next_due is not None and self.elapsed_seconds >= self._next_due:
            self._prompt = BreakPrompt(str(uuid4()), self.session_id)
        return self._prompt

    def answer_reminder(self, prompt_id, action):
        if self._prompt is None or self._prompt.prompt_id != prompt_id or self.state != "working":
            return False
        if action not in {"take_break", "snooze", "dismiss"}:
            raise ValueError("Choose Take break, Snooze or Dismiss.")
        if action == "take_break":
            return self.pause()
        delay = 300 if action == "snooze" else self.reminder_interval_seconds
        self._next_due, self._prompt = self.elapsed_seconds + delay, None
        return True


def checkin_record(point, *, session_id="standalone", clarity="skipped"):
    """Keep the existing point answer, with separate optional clarity/session context."""
    if point.scope != "point" or clarity not in CLARITY_VALUES:
        raise ValueError("Use a point check-in and a supported clarity choice.")
    return {"id": point.response_id, "answered_at": point.answered_at.isoformat(), "session_id": session_id,
            "stress_state": point.state, "stress_value": point.value, "clarity": clarity}
