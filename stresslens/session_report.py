"""Bounded numeric reflection reports. No camera, SDK, files or device access.

Lock order is workspace -> accumulator. Neither lock owns a worker or joins a
thread. The future camera adapter must finish a segment before live cleanup;
this module cannot start, stop or establish release of a physical camera.
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from uuid import uuid4


FEATURE_LABELS = (
    "Brow lowering", "Eye narrowing", "Lip pressing",
    "Smile shape", "Eye closure", "Jaw opening",
)
STOP_REASONS = frozenset({
    "timer_end", "user_off", "resource_limit", "capture_error",
    "consent_revoked", "inactivity",
})
LIMITATIONS = (
    "Facial movements are not inferred stress, emotions or a diagnosis.",
    "Self-reported stress is the user's answer, not a validated clinical scale.",
    "Camera-off periods have no facial observations; missing slots are not filled.",
    "Coverage thresholds and resource limits are provisional engineering choices.",
    "SDK, real camera, UI, device alignment and scientific validity are not validated by this module.",
)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected a finite number")
    return float(value)


def _utc(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("An explicit timezone-aware timestamp is required")
    return value.astimezone(UTC)


def _text(value, label, limit=120):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid {label}")
    return value


def _slots(seconds, rounding=ROUND_CEILING):
    return int((Decimal(str(seconds)) * 10).to_integral_value(rounding=rounding))


def _groups(values):
    if set(values) != set(FEATURE_LABELS):
        raise ValueError("Expected the six existing facial movement groups")
    result = tuple(_number(values[name]) for name in FEATURE_LABELS)
    if any(not 0 <= x <= 1 for x in result):
        raise ValueError("Movement coefficients must be within 0..1")
    return result


@dataclass(frozen=True)
class SegmentConfig:
    timer_seconds: int | None = None
    activity: str = "other"
    checkin_mode: str = "everyday"

    def __post_init__(self):
        timer = self.timer_seconds
        if timer is not None and (type(timer) is not int or not 1 <= timer <= 3600):
            raise ValueError("Timer must be None or a whole number of seconds in 1..3600")
        _text(self.activity, "activity")
        if self.checkin_mode not in {"everyday", "research"}:
            raise ValueError("Choose everyday or research check-ins")

    @property
    def deadline(self):
        return self.timer_seconds if self.timer_seconds is not None else 3600


@dataclass(frozen=True)
class FeatureAggregate:
    name: str
    valid_count: int
    mean: float | None
    minimum: float | None
    maximum: float | None


@dataclass(frozen=True)
class FacialWindow:
    start_seconds: float
    end_seconds: float
    expected_slots: int
    valid_slots: int
    coverage: float
    max_gap_seconds: float
    reason_counts: tuple[tuple[str, int], ...]
    usable: bool
    features: tuple[FeatureAggregate, ...]


@dataclass(frozen=True)
class SegmentReport:
    segment_id: str
    config: SegmentConfig
    start_utc: datetime
    end_utc: datetime
    duration_seconds: float
    reason: str
    complete: bool
    facial_windows: tuple[FacialWindow, ...]
    reference: tuple[tuple[str, float], ...] | None
    expected_slots: int
    valid_slots: int
    coverage: float
    max_gap_seconds: float
    sampling_hz: float
    rejected_observations: int
    brief: bool
    trend_available: bool


class SegmentAccumulator:
    """At most 200 current-window numeric slots and 180 reduced windows."""

    def __init__(self, config, segment_id, start_utc, start_monotonic):
        if not isinstance(config, SegmentConfig):
            raise ValueError("A SegmentConfig is required")
        self.config = config
        self.segment_id = _text(segment_id, "segment ID")
        self.start_utc = _utc(start_utc)
        self.start_monotonic = _number(start_monotonic)
        self._lock = threading.RLock()
        self._current = {}
        self._window_index = 0
        self._windows = []
        self._last_slot = -1
        self._last_elapsed = 0.0
        self._rejected = 0
        self._observations = 0
        self._reference = None
        self._report = None
        self._trailing_gap = 0.0
        self._max_gap = 0.0

    def set_reference(self, values):
        normalized = _groups(values)
        with self._lock:
            if self._report is not None:
                raise RuntimeError("Finalized segment cannot change its reference")
            self._reference = tuple(zip(FEATURE_LABELS, normalized, strict=True))

    def observe(self, elapsed_seconds, groups, unavailable_reason=None):
        with self._lock:
            if self._report is not None:
                return False
            try:
                elapsed = _number(elapsed_seconds)
                slot = _slots(elapsed, ROUND_FLOOR)
                if elapsed < self._last_elapsed or elapsed < 0 or elapsed >= self.config.deadline or slot <= self._last_slot:
                    raise ValueError("Observation is backward, duplicate or outside the segment")
                normalized = _groups(groups) if groups else None
                reason = None if normalized else _text(unavailable_reason or "unavailable", "unavailability reason", 80)
            except (TypeError, ValueError):
                self._rejected += 1
                return False
            target_window = slot // 200
            while self._window_index < target_window:
                self._close_window((self._window_index + 1) * 20)
            self._current[slot % 200] = (elapsed, normalized, reason)
            self._last_slot = slot
            self._last_elapsed = elapsed
            return True

    def _close_window(self, end):
        start = self._window_index * 20
        expected = min(200, max(0, _slots(end) - self._window_index * 200))
        values = []
        reasons = Counter()
        run_start = None
        max_gap = 0.0
        prefix = None
        for i in range(expected):
            observed_at, row, reason = self._current.get(i, (None, None, "unsampled"))
            if observed_at is not None:
                if observed_at >= end:
                    row, reason = None, "unsampled"
                    self._rejected += 1
                else:
                    self._observations += 1
            slot_start = start + i / 10
            if row is None:
                reasons[reason] += 1
                if run_start is None:
                    run_start = slot_start
            else:
                if prefix is None:
                    prefix = slot_start - start
                if run_start is not None:
                    max_gap = max(max_gap, slot_start - run_start)
                    run_start = None
                values.append(row)
        trailing = end - run_start if run_start is not None else 0.0
        max_gap = max(max_gap, trailing)
        prefix = end - start if prefix is None else prefix
        self._max_gap = max(self._max_gap, max_gap, self._trailing_gap + prefix)
        self._trailing_gap = self._trailing_gap + trailing if not values else trailing
        valid = len(values)
        coverage = valid / expected if expected else 0.0
        usable = expected > 0 and coverage >= 0.8 and max_gap <= 2.0 + 1e-9
        features = []
        for index, name in enumerate(FEATURE_LABELS):
            column = [row[index] for row in values]
            features.append(FeatureAggregate(
                name, valid, sum(column) / valid if usable else None,
                min(column) if usable else None, max(column) if usable else None,
            ))
        self._windows.append(FacialWindow(
            start, end, expected, valid, coverage, max_gap,
            tuple(sorted(reasons.items())), usable, tuple(features),
        ))
        self._current.clear()
        self._window_index += 1

    def finalize(self, elapsed_seconds, reason):
        with self._lock:
            if self._report is not None:
                return self._report
            elapsed = _number(elapsed_seconds)
            if elapsed < 0 or elapsed < self._last_elapsed or reason not in STOP_REASONS:
                raise ValueError("Invalid finalization time or terminal reason")
            duration = min(elapsed, self.config.deadline)
            if elapsed >= self.config.deadline:
                reason = "timer_end" if self.config.timer_seconds is not None else "resource_limit"
            elif reason in {"timer_end", "resource_limit"}:
                raise ValueError("A deadline reason cannot end before its deadline")
            while self._window_index * 20 < duration:
                self._close_window(min(duration, (self._window_index + 1) * 20))
            # A callback at the exact stop/window edge may be awaiting a new
            # window; it is outside [start, end), including at zero duration.
            self._rejected += len(self._current)
            expected = sum(w.expected_slots for w in self._windows)
            valid = sum(w.valid_slots for w in self._windows)
            self._report = SegmentReport(
                self.segment_id, self.config, self.start_utc,
                self.start_utc + timedelta(seconds=duration), duration, reason,
                reason in {"user_off", "timer_end"}, tuple(self._windows),
                self._reference, expected, valid, valid / expected if expected else 0.0,
                self._max_gap, self._observations / duration if duration else 0.0,
                self._rejected, 0 < duration < 20,
                sum(w.usable for w in self._windows) >= 2,
            )
            self._current.clear()
            return self._report


@dataclass(frozen=True)
class SelfReport:
    response_id: str
    answered_at: datetime
    state: str
    value: int | None = None
    scope: str = "point"
    segment_id: str | None = None
    interval_start: int | None = None
    interval_end: int | None = None
    question_version: str = "stress-checkin/1"
    scale_version: str = "none-low-high/1"
    question: str = field(init=False)

    def __post_init__(self):
        _text(self.response_id, "response ID")
        object.__setattr__(self, "answered_at", _utc(self.answered_at))
        if self.state not in {"answered", "unsure", "skipped", "expired"}:
            raise ValueError("Unknown response state")
        if self.state == "answered":
            if type(self.value) is not int or self.value not in {0, 1, 2}:
                raise ValueError("Answered ratings require 0, 1 or 2")
        elif self.value is not None:
            raise ValueError("Missing-label states cannot have a value")
        if self.scope == "point":
            if self.interval_start is not None or self.interval_end is not None:
                raise ValueError("Point answers cannot label an interval")
        elif self.scope == "interval":
            if not self.segment_id or type(self.interval_start) is not int or type(self.interval_end) is not int:
                raise ValueError("An interval requires a segment and integer endpoints")
            if self.interval_start < 0 or self.interval_start % 120 or self.interval_end != self.interval_start + 120:
                raise ValueError("Research intervals are complete non-overlapping 120-second intervals")
        else:
            raise ValueError("Unknown rating scope")
        _text(self.question_version, "question version")
        _text(self.scale_version, "scale version")
        object.__setattr__(self, "question", "How stressed do you feel right now?" if self.scope == "point"
                           else "Thinking about the last two minutes, how stressed did you feel?")


@dataclass(frozen=True)
class Measurement:
    """Typed numeric storage boundary only; CSV/device ingestion is a later task."""

    source_id: str
    timestamp: datetime
    metric: str
    value: float
    unit: str
    device: str
    method: str
    ingested_at: datetime
    value_secondary: float | None = None
    segment_id: str | None = None

    def __post_init__(self):
        for name in ("source_id", "device", "method"):
            _text(getattr(self, name), name)
        object.__setattr__(self, "timestamp", _utc(self.timestamp))
        object.__setattr__(self, "ingested_at", _utc(self.ingested_at))
        units = {"heart_rate": "bpm", "hrv_sdnn": "ms", "blood_pressure": "mmHg"}
        if self.metric not in units or self.unit != units[self.metric] or _number(self.value) <= 0:
            raise ValueError("Unsupported measurement or nonpositive value")
        if self.metric == "blood_pressure":
            if not 0 < _number(self.value_secondary) < self.value:
                raise ValueError("Blood pressure requires a valid paired diastolic value")
        elif self.value_secondary is not None:
            raise ValueError("Only blood pressure has a secondary value")


def _measurement_source_key(row):
    """Identity of the original reading, excluding ingestion and association."""
    return (row.source_id, row.timestamp, row.metric, row.value, row.value_secondary,
            row.unit, row.device, row.method)


@dataclass(frozen=True)
class ReportSnapshot:
    report_id: str | None
    revision: int
    display_timezone: str
    segments: tuple[SegmentReport, ...]
    self_reports: tuple[SelfReport, ...]
    measurements: tuple[Measurement, ...]
    active_segment_id: str | None


class ReportWorkspace:
    """Persistent numeric workspace; opening it neither allocates an ID nor captures."""

    def __init__(self, clock=time.monotonic, display_timezone="UTC"):
        self._clock = clock
        self._display_timezone = _text(display_timezone, "display timezone", 80)
        self._lock = threading.RLock()
        self._report_id = None
        self._revision = 0
        self._segments = []
        self._self_reports = []
        self._measurements = {}
        self._active = None

    def _touch(self):
        if self._report_id is None:
            self._report_id = str(uuid4())
        self._revision += 1

    def start_segment(self, config, start_utc, start_monotonic):
        with self._lock:
            if self._active is not None:
                return self._active
            if len(self._segments) >= 10:
                raise ValueError("Ten segments retained; export/clear before another")
            candidate = SegmentAccumulator(config, str(uuid4()), start_utc, start_monotonic)
            if self._segments and candidate.start_utc < self._segments[-1].end_utc:
                raise ValueError("Segments must not overlap or go backward")
            self._active = candidate
            self._touch()
            return candidate

    def finish_segment(self, elapsed_seconds, reason):
        with self._lock:
            if self._active is None:
                return self._segments[-1] if self._segments else None
            report = self._active.finalize(elapsed_seconds, reason)
            self._segments.append(report)
            self._active = None
            self._touch()
            return report

    def _association(self, timestamp):
        for segment in self._segments:
            if segment.start_utc <= timestamp < segment.end_utc:
                return segment.segment_id
        if self._active is not None:
            a = self._active
            end = a.start_utc + timedelta(seconds=min(a.config.deadline, max(0, self._clock() - a.start_monotonic)))
            if a.start_utc <= timestamp < end:
                return a.segment_id
        return None

    def add_self_report(self, response):
        if not isinstance(response, SelfReport):
            raise ValueError("A typed SelfReport is required")
        with self._lock:
            if len(self._self_reports) >= 1000:
                raise ValueError("1000 check-ins retained; export/clear before adding")
            if any(r.response_id == response.response_id for r in self._self_reports):
                raise ValueError("Duplicate response ID")
            if response.scope == "point":
                associated = self._association(response.answered_at)
                if response.segment_id is not None and response.segment_id != associated:
                    raise ValueError("Point association does not match the answer time")
                response = replace(response, segment_id=associated)
            else:
                segment = next((s for s in self._segments if s.segment_id == response.segment_id), None)
                if segment is None and self._active is not None and self._active.segment_id == response.segment_id:
                    segment = self._active
                    duration = min(segment.config.deadline, max(0, self._clock() - segment.start_monotonic))
                else:
                    duration = segment.duration_seconds if segment else 0
                if segment is None or segment.config.checkin_mode != "research" or response.interval_end > duration:
                    raise ValueError("Interval lacks a complete observed research segment")
                prompt_at = segment.start_utc + timedelta(seconds=response.interval_end)
                expires_at = prompt_at + timedelta(seconds=30)
                if response.answered_at < prompt_at:
                    raise ValueError("Interval has not ended")
                if (response.state == "expired") != (response.answered_at > expires_at):
                    raise ValueError("Interval answer is late or not yet expired")
                if any(r.scope == "interval" and r.segment_id == response.segment_id and
                       r.interval_start == response.interval_start for r in self._self_reports):
                    raise ValueError("Interval already has a response")
            self._self_reports.append(response)
            self._touch()

    def add_measurements(self, rows):
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Measurements may only be added with camera OFF")
            pending = {}
            for row in rows:
                if not isinstance(row, Measurement):
                    raise ValueError("Typed numeric measurements are required")
                row = replace(row, segment_id=self._association(row.timestamp))
                existing = pending.get(row.source_id, self._measurements.get(row.source_id))
                if existing is not None:
                    if _measurement_source_key(existing) != _measurement_source_key(row):
                        raise ValueError("Conflicting measurement source ID")
                    continue  # Retain the first stored/pending ingestion provenance.
                pending[row.source_id] = row
                if len(self._measurements) + len(pending) > 10000:
                    raise ValueError("10000 measurements retained; export/clear before adding")
            if pending:
                self._measurements.update(pending)
                self._touch()

    def snapshot(self):
        with self._lock:
            return ReportSnapshot(
                self._report_id, self._revision, self._display_timezone,
                tuple(self._segments), tuple(self._self_reports),
                tuple(self._measurements.values()),
                self._active.segment_id if self._active is not None else None,
            )

    def clear(self):
        with self._lock:
            if self._active is not None:
                raise RuntimeError("Finish/release capture before clearing its numeric workspace")
            self._segments.clear()
            self._self_reports.clear()
            self._measurements.clear()
            self._report_id = None
            self._revision = 0


def _plain(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    return value


def to_export(snapshot, include_measurements=False):
    """Return a detached JSON-safe snapshot; device observations are opt-in."""
    if type(include_measurements) is not bool:
        raise ValueError("Measurement export requires an explicit boolean choice")
    if not isinstance(snapshot, ReportSnapshot):
        raise ValueError("An immutable ReportSnapshot is required")
    if snapshot.active_segment_id is not None:
        raise RuntimeError("Export is available only with camera OFF")
    segments = snapshot.segments
    timestamps = [t for s in segments for t in (s.start_utc, s.end_utc)]
    timestamps.extend(r.answered_at for r in snapshot.self_reports)
    if include_measurements:
        timestamps.extend(r.timestamp for r in snapshot.measurements)
    start = min(timestamps) if timestamps else None
    end = max(timestamps) if timestamps else None
    gaps = []
    cursor = start
    for segment in segments:
        if cursor is not None and cursor < segment.start_utc:
            gaps.append({"start_utc": cursor, "end_utc": segment.start_utc,
                         "duration_seconds": (segment.start_utc - cursor).total_seconds(),
                         "facial_observations": False})
        cursor = segment.end_utc
    if cursor is not None and end is not None and cursor < end:
        gaps.append({"start_utc": cursor, "end_utc": end,
                     "duration_seconds": (end - cursor).total_seconds(),
                     "facial_observations": False})
    expected = sum(s.expected_slots for s in segments)
    valid = sum(s.valid_slots for s in segments)
    payload = {
        "schema": "session-report/2",
        "session": {
            "report_id": snapshot.report_id, "revision": snapshot.revision,
            "display_timezone": snapshot.display_timezone,
            "start_utc": start, "end_utc": end,
            "span_seconds": (end - start).total_seconds() if start is not None else 0,
            "camera_on_seconds": sum(s.duration_seconds for s in segments),
            "expected_slots": expected, "valid_slots": valid,
            "coverage": valid / expected if expected else 0.0,
            "usable_windows": sum(w.usable for s in segments for w in s.facial_windows),
        },
        "segments": [asdict(s) for s in segments],
        "off_camera_periods": gaps,
        "self_reports": [asdict(r) for r in snapshot.self_reports],
        "provenance": {
            "algorithm_version": "slot-coverage/1", "window_seconds": 20,
            "slot_seconds": 0.1, "minimum_coverage": 0.8, "maximum_gap_seconds": 2,
            "segment_cap_seconds": 3600, "segment_cap": 10,
            "self_report_cap": 1000, "measurement_cap": 10000,
            "reference_meaning": "Optional expression comparison; never a calm baseline",
        },
        "limitations": list(LIMITATIONS),
    }
    if include_measurements:
        payload["measurements"] = [asdict(r) for r in snapshot.measurements]
    return _plain(payload)


def to_text(snapshot, include_measurements=False):
    payload = to_export(snapshot, include_measurements)
    session = payload["session"]
    lines = [
        "StressLens reflection report — numeric observations only",
        f"Camera-on duration: {session['camera_on_seconds']:g} seconds",
        f"Overall report span: {session['span_seconds']:g} seconds",
        f"Usable camera slots: {session['valid_slots']} / {session['expected_slots']}",
        "Facial movement: separate segments; gaps have no facial observations.",
        "Self-reported stress: the user's answers, not an automatic stress estimate.",
        "Device observations: explicitly included." if include_measurements else "Device observations: excluded from this download.",
        "", "Report details (timestamps in UTC; separate units retained):",
        json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2),
    ]
    return "\n".join(lines) + "\n"
