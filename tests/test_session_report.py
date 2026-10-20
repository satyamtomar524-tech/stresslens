"""Synthetic revision-2 contracts; no media, camera, SDK or participant data."""
import dataclasses
import importlib
import importlib.util
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest


START = datetime(2026, 10, 15, 12, tzinfo=UTC)
GROUPS = {
    "Brow lowering": 0.25, "Eye narrowing": 0.25, "Lip pressing": 0.25,
    "Smile shape": 0.25, "Eye closure": 0.25, "Jaw opening": 0.25,
}


def api():
    assert importlib.util.find_spec("stresslens.session_report") is not None, (
        "The pure revision-2 report module has not been implemented"
    )
    return importlib.import_module("stresslens.session_report")


def accumulator(m, timer=None, mode="everyday"):
    return m.SegmentAccumulator(m.SegmentConfig(timer, "study", mode), "synthetic-1", START, 0)


def point(m, record_id="point-1", seconds=0, state="answered", value=1):
    return m.SelfReport(record_id, START + timedelta(seconds=seconds), state, value)


def interval(m, segment_id, record_id="interval-1", answer=121, end=120, state="answered"):
    return m.SelfReport(
        record_id, START + timedelta(seconds=answer), state,
        2 if state == "answered" else None, scope="interval", segment_id=segment_id,
        interval_start=max(0, end - 120), interval_end=end,
    )


def test_camera_free_report_is_lazy_and_snapshots_are_immutable():
    m = api()
    w = m.ReportWorkspace()
    empty = w.snapshot()
    assert empty.report_id is None
    assert empty.segments == () and empty.self_reports == ()
    w.add_self_report(point(m))
    first = w.snapshot()
    assert first.report_id and first.self_reports[0].segment_id is None
    assert first.self_reports[0].value == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.revision = 999
    exported = m.to_export(first)
    exported["self_reports"][0]["value"] = 0
    assert w.snapshot().self_reports[0].value == 1
    w.add_self_report(point(m, "point-2", 5, "unsure", None))
    assert len(first.self_reports) == 1
    assert w.snapshot().revision > first.revision


@pytest.mark.parametrize("duration,windows,slots", [
    (0, 0, 0), (1, 1, 10), (2, 1, 20), (19, 1, 190), (20, 1, 200),
    (21, 2, 210), (600, 30, 6000), (1000, 50, 10000),
    (1200, 60, 12000), (3600, 180, 36000),
])
def test_arbitrary_durations_keep_missing_time_and_bounded_windows(duration, windows, slots):
    m = api()
    report = accumulator(m).finalize(duration, "user_off")
    assert report.duration_seconds == duration
    assert len(report.facial_windows) == windows
    assert sum(x.expected_slots for x in report.facial_windows) == slots
    assert report.valid_slots == 0
    assert report.coverage == 0
    assert all(x.features[0].mean is None for x in report.facial_windows)
    assert report.brief is (0 < duration < 20)
    if duration == 3600:
        assert report.reason == "resource_limit"


@pytest.mark.parametrize("timer", [True, False, 0, -1, 3601, 1.0, "10", float("nan")])
def test_timer_rejects_non_integer_or_out_of_range_values(timer):
    m = api()
    with pytest.raises(ValueError):
        m.SegmentConfig(timer)


@pytest.mark.parametrize("timer,elapsed,duration,reason", [
    (None, 1, 1, "user_off"), (2, 5, 2, "timer_end"),
    (600, 1000, 600, "timer_end"), (None, 5000, 3600, "resource_limit"),
])
def test_deadlines_clamp_duration_and_choose_honest_terminal_reason(timer, elapsed, duration, reason):
    m = api()
    a = accumulator(m, timer)
    assert not a.observe(4000, GROUPS)
    r = a.finalize(elapsed, "user_off")
    assert (r.duration_seconds, r.reason) == (duration, reason)
    assert a.finalize(9999, "capture_error") is r


@pytest.mark.parametrize("reason,complete", [
    ("user_off", True), ("capture_error", False),
    ("consent_revoked", False), ("inactivity", False),
])
def test_early_stop_preserves_interruption_reason(reason, complete):
    m = api()
    r = accumulator(m).finalize(2, reason)
    assert (r.reason, r.complete) == (reason, complete)


def test_partial_window_counts_elapsed_slots_and_does_not_invent_a_trend():
    m = api()
    a = accumulator(m)
    for t in [0, 0.1, 0.2]:
        assert a.observe(t, GROUPS)
    r = a.finalize(0.25, "user_off")
    x = r.facial_windows[0]
    assert (x.expected_slots, x.valid_slots, x.coverage) == (3, 3, 1)
    assert x.features[0].mean == 0.25
    assert r.brief and not r.trend_available


@pytest.mark.parametrize("pattern,valid,gap,usable", [
    ("eighty", 160, 0.1, True), ("below_eighty", 159, 0.2, False),
    ("two_seconds", 180, 2.0, True), ("over_two", 179, 2.1, False),
])
def test_quality_boundaries_suppress_unusable_values(pattern, valid, gap, usable):
    m = api()
    a = accumulator(m)
    for i in range(200):
        missing = i % 5 == 0 if pattern in {"eighty", "below_eighty"} else 80 <= i < (100 if pattern == "two_seconds" else 101)
        missing = missing or (pattern == "below_eighty" and i == 1)
        a.observe(i / 10, {} if missing else GROUPS, "no_face" if missing else None)
    x = a.finalize(20, "user_off").facial_windows[0]
    assert x.valid_slots == valid
    assert x.max_gap_seconds == pytest.approx(gap)
    assert x.usable is usable
    assert x.features[0].valid_count == valid
    assert x.features[0].mean == (0.25 if usable else None)


def test_missing_runs_span_window_boundaries_without_forward_fill():
    m = api()
    a = accumulator(m)
    for i in list(range(190)) + list(range(211, 400)):
        a.observe(i / 10, GROUPS)
    r = a.finalize(40, "user_off")
    assert [x.valid_slots for x in r.facial_windows] == [190, 189]
    assert r.max_gap_seconds == pytest.approx(2.1)
    assert dict(r.facial_windows[0].reason_counts) == {"unsampled": 10}
    assert dict(r.facial_windows[1].reason_counts) == {"unsampled": 11}


def test_duplicate_backward_invalid_and_post_deadline_observations_are_rejected():
    m = api()
    a = accumulator(m, 2)
    assert a.observe(0.1, GROUPS)
    for t in [0.1, 0, 2, -1, float("nan")]:
        assert not a.observe(t, GROUPS)
    r = a.finalize(1, "user_off")
    assert r.rejected_observations == 5
    assert r.valid_slots == 1 and r.expected_slots == 10
    assert not a.observe(1.1, GROUPS)
    assert r.rejected_observations == 5


def test_new_segments_isolate_reference_and_exclude_camera_off_gaps():
    m = api()
    w = m.ReportWorkspace()
    a = w.start_segment(m.SegmentConfig(), START, 0)
    a.set_reference(GROUPS)
    for i in range(30):
        a.observe(i / 10, GROUPS)
    assert w.start_segment(m.SegmentConfig(2), START, 99) is a
    first = w.finish_segment(3, "user_off")
    assert w.finish_segment(3, "capture_error") is first
    w.add_self_report(point(m, seconds=3))
    b = w.start_segment(m.SegmentConfig(), START + timedelta(seconds=10), 10)
    assert b.segment_id != a.segment_id
    for i in range(20):
        b.observe(i / 10, {k: 0.75 for k in GROUPS})
    w.finish_segment(2, "user_off")
    snapshot = w.snapshot()
    assert snapshot.segments[0] is first
    assert snapshot.segments[1].reference is None
    assert first.reference is not None
    assert snapshot.self_reports[0].segment_id is None
    exported = m.to_export(snapshot)
    assert exported["session"]["camera_on_seconds"] == 5
    assert exported["session"]["span_seconds"] == 12
    assert exported["session"]["expected_slots"] == 50
    assert exported["off_camera_periods"][0]["duration_seconds"] == 7
    assert exported["off_camera_periods"][0]["facial_observations"] is False


def test_active_export_is_blocked_and_clear_resets_all_numeric_state():
    m = api()
    w = m.ReportWorkspace()
    w.add_self_report(point(m))
    old_id = w.snapshot().report_id
    w.start_segment(m.SegmentConfig(), START, 0)
    with pytest.raises(RuntimeError):
        m.to_export(w.snapshot())
    with pytest.raises(RuntimeError):
        w.clear()
    w.finish_segment(0, "user_off")
    w.clear()
    assert w.snapshot().report_id is None
    assert w.snapshot().segments == () and w.snapshot().self_reports == ()
    w.add_self_report(point(m, "fresh"))
    assert w.snapshot().report_id != old_id


def test_segment_and_rating_caps_reject_without_eviction():
    m = api()
    w = m.ReportWorkspace()
    for i in range(10):
        w.start_segment(m.SegmentConfig(), START + timedelta(seconds=i * 4000), i * 4000)
        w.finish_segment(3600, "resource_limit")
    before = w.snapshot()
    assert sum(len(s.facial_windows) for s in before.segments) == 1800
    with pytest.raises(ValueError):
        w.start_segment(m.SegmentConfig(), START + timedelta(seconds=40000), 40000)
    assert w.snapshot() == before
    for i in range(1000):
        w.add_self_report(point(m, str(i), seconds=50000 + i))
    with pytest.raises(ValueError):
        w.add_self_report(point(m, "overflow", seconds=60000))
    assert len(w.snapshot().self_reports) == 1000


def test_research_interval_survives_stop_but_cannot_cross_gap_or_expiry():
    m = api()
    w = m.ReportWorkspace()
    a = w.start_segment(m.SegmentConfig(None, "study", "research"), START, 0)
    w.finish_segment(120, "user_off")
    w.add_self_report(interval(m, a.segment_id))
    w.add_self_report(point(m, "end-point", seconds=121))
    records = w.snapshot().self_reports
    assert records[0].segment_id == a.segment_id and records[0].scope == "interval"
    assert records[1].segment_id is None and records[1].scope == "point"
    for row in [interval(m, a.segment_id, "duplicate"),
                interval(m, a.segment_id, "late", answer=151),
                interval(m, a.segment_id, "partial", answer=241, end=240)]:
        with pytest.raises(ValueError):
            w.add_self_report(row)


def test_interval_requires_research_mode_and_exact_complete_interval():
    m = api()
    w = m.ReportWorkspace()
    a = w.start_segment(m.SegmentConfig(), START, 0)
    w.finish_segment(120, "user_off")
    with pytest.raises(ValueError):
        w.add_self_report(interval(m, a.segment_id))
    w.clear()
    a = w.start_segment(m.SegmentConfig(None, "study", "research"), START, 0)
    w.finish_segment(120, "user_off")
    with pytest.raises(ValueError):
        w.add_self_report(interval(m, a.segment_id, end=119))
    w.add_self_report(interval(m, a.segment_id, state="expired", answer=151))
    assert w.snapshot().self_reports[0].value is None


@pytest.mark.parametrize("state,value", [("answered", None), ("answered", 3),
                                         ("answered", True), ("unsure", 1), ("bad", None)])
def test_rating_schema_rejects_fabricated_values(state, value):
    m = api()
    with pytest.raises(ValueError):
        point(m, state=state, value=value)


def test_measurement_retention_is_atomic_bounded_and_omitted_by_default():
    m = api()
    w = m.ReportWorkspace()
    rows = [m.Measurement(str(i), START, "heart_rate", 70, "bpm", "fictional", "synthetic", START)
            for i in range(10000)]
    w.add_measurements(rows)
    snapshot = w.snapshot()
    w.add_measurements(rows[:1])
    assert w.snapshot() == snapshot
    with pytest.raises(ValueError):
        w.add_measurements([dataclasses.replace(rows[0], source_id="overflow")])
    with pytest.raises(ValueError):
        w.add_measurements([dataclasses.replace(rows[0], value=75)])
    assert w.snapshot() == snapshot
    assert "measurements" not in m.to_export(snapshot)
    assert "bpm" not in m.to_text(snapshot)
    included = m.to_export(snapshot, include_measurements=True)
    assert len(included["measurements"]) == 10000
    assert included["measurements"][0]["segment_id"] is None
    assert "bpm" in m.to_text(snapshot, include_measurements=True)


def test_finalization_is_thread_safe_and_does_not_accept_late_mutation():
    m = api()
    a = accumulator(m)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: a.finalize(1, "user_off"), range(8)))
    assert all(r is results[0] for r in results)
    with pytest.raises(RuntimeError):
        a.set_reference(GROUPS)
    with pytest.raises(dataclasses.FrozenInstanceError):
        results[0].facial_windows[0].expected_slots = 0


def test_plain_import_and_camera_free_rating_have_no_sdk_dependencies():
    api()
    script = """
import sys
from datetime import UTC, datetime
from stresslens.session_report import ReportWorkspace, SelfReport, to_export
w = ReportWorkspace()
w.add_self_report(SelfReport('synthetic', datetime(2026, 1, 1, tzinfo=UTC), 'answered', 1))
assert to_export(w.snapshot())['self_reports'][0]['segment_id'] is None
assert not {'mediapipe', 'cv2', 'numpy', 'streamlit'} & sys.modules.keys()
"""
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_json_text_exports_share_schema_and_have_no_inferred_stress():
    m = api()
    w = m.ReportWorkspace()
    w.add_self_report(point(m, seconds=-1))
    a = w.start_segment(m.SegmentConfig(1), START, 0)
    a.observe(0, GROUPS)
    w.finish_segment(1, "timer_end")
    payload = m.to_export(w.snapshot())
    encoded = json.dumps(payload, allow_nan=False)
    assert json.loads(encoded)["schema"] == "session-report/2"
    assert "Self-reported stress" in m.to_text(w.snapshot())
    assert not {"stress_probability", "predicted_stress", "stress_score", "images", "audio"} & payload.keys()
    assert payload["provenance"]["algorithm_version"]


@pytest.mark.parametrize("end,valid,rate", [(20, 2, 0.1), (21, 3, 3 / 21)])
def test_half_open_window_and_stop_boundaries_exclude_final_callbacks(end, valid, rate):
    m = api()
    a = accumulator(m)
    for t in [0.01, 19.91, 20]:
        a.observe(t, GROUPS)
    report = a.finalize(end, "user_off")
    assert report.valid_slots == valid
    assert report.sampling_hz == pytest.approx(rate)
    assert report.facial_windows[0].valid_slots == 2
    if end == 21:
        assert report.facial_windows[1].valid_slots == 1


def test_partial_last_slot_keeps_actual_gap_and_excludes_a_stop_time_callback():
    m = api()
    a = accumulator(m)
    for t in [0.01, 0.11, 0.25]:
        a.observe(t, GROUPS)
    report = a.finalize(0.25, "user_off")
    window = report.facial_windows[0]
    assert (window.expected_slots, window.valid_slots) == (3, 2)
    assert window.max_gap_seconds == pytest.approx(0.05)
    assert report.sampling_hz == 8


def test_bad_features_do_not_poison_a_slot_and_first_accepted_callback_wins():
    m = api()
    a = accumulator(m)
    bad = dict(GROUPS, **{"Jaw opening": float("nan")})
    assert not a.observe(0, bad)
    assert not a.observe(0, {"Jaw opening": 0.2})
    assert a.observe(0.01, GROUPS)
    assert a.observe(0.11, {}, "no_face")
    assert not a.observe(0.12, GROUPS)
    report = a.finalize(1, "user_off")
    assert report.valid_slots == 1 and report.rejected_observations == 3
    assert dict(report.facial_windows[0].reason_counts) == {"no_face": 1, "unsampled": 8}


@pytest.mark.parametrize("include", ["false", 1, None])
def test_device_export_requires_a_real_explicit_boolean(include):
    m = api()
    snapshot = m.ReportWorkspace().snapshot()
    for export in (m.to_export, m.to_text):
        with pytest.raises(ValueError):
            export(snapshot, include_measurements=include)


def test_exports_retain_exact_point_and_interval_questions():
    m = api()
    w = m.ReportWorkspace()
    w.add_self_report(point(m))
    a = w.start_segment(m.SegmentConfig(None, "study", "research"), START, 0)
    w.finish_segment(120, "user_off")
    w.add_self_report(interval(m, a.segment_id))
    exported = m.to_export(w.snapshot())
    assert exported["self_reports"][0]["question"] == "How stressed do you feel right now?"
    assert exported["self_reports"][1]["question"] == "Thinking about the last two minutes, how stressed did you feel?"


def f1_measurement(m, **changes):
    base = m.Measurement("same-source", START, "heart_rate", 70, "bpm", "fictional", "synthetic",
                         START + timedelta(seconds=1))
    return dataclasses.replace(base, **changes)


def test_f1_later_ingestion_duplicate_keeps_original_record_and_revision():
    m = api()
    w = m.ReportWorkspace()
    original = f1_measurement(m)
    w.add_measurements([original])
    before = w.snapshot()
    w.add_measurements([dataclasses.replace(original, ingested_at=START + timedelta(seconds=2), segment_id="derived")])
    after = w.snapshot()
    assert after == before
    assert after.measurements[0] is before.measurements[0]
    assert after.measurements[0].ingested_at == START + timedelta(seconds=1)


def test_f1_duplicate_plus_new_batch_commits_only_new_source_reading():
    m = api()
    w = m.ReportWorkspace()
    original = f1_measurement(m)
    w.add_measurements([original])
    before = w.snapshot()
    duplicate = dataclasses.replace(original, ingested_at=START + timedelta(seconds=2))
    new = f1_measurement(m, source_id="new-source", timestamp=START + timedelta(seconds=10))
    w.add_measurements([duplicate, new])
    after = w.snapshot()
    assert [r.source_id for r in after.measurements] == ["same-source", "new-source"]
    assert after.measurements[0] is before.measurements[0]
    assert after.revision == before.revision + 1


def test_f1_same_batch_duplicate_preserves_first_ingestion_provenance():
    m = api()
    w = m.ReportWorkspace()
    first = f1_measurement(m)
    w.add_measurements([first, dataclasses.replace(first, ingested_at=START + timedelta(seconds=2))])
    assert len(w.snapshot().measurements) == 1
    assert w.snapshot().measurements[0].ingested_at == START + timedelta(seconds=1)


@pytest.mark.parametrize("changes", [
    {"timestamp": START + timedelta(seconds=1)}, {"value": 71},
    {"device": "different"}, {"method": "different"}, {"metric": "hrv_sdnn", "unit": "ms"},
])
def test_f1_true_source_conflicts_reject_all_pending_changes(changes):
    m = api()
    w = m.ReportWorkspace()
    original = f1_measurement(m)
    w.add_measurements([original])
    before = w.snapshot()
    new = f1_measurement(m, source_id="pending-new")
    conflict = dataclasses.replace(original, **changes, ingested_at=START + timedelta(seconds=2))
    with pytest.raises(ValueError, match="Conflicting"):
        w.add_measurements([new, conflict])
    assert w.snapshot() == before


def test_f1_mixed_new_duplicate_conflict_batch_is_atomic():
    m = api()
    w = m.ReportWorkspace()
    original = f1_measurement(m)
    w.add_measurements([original])
    before = w.snapshot()
    duplicate = dataclasses.replace(original, ingested_at=START + timedelta(seconds=2))
    new = f1_measurement(m, source_id="pending-new")
    conflict = dataclasses.replace(original, value=71)
    with pytest.raises(ValueError, match="Conflicting"):
        w.add_measurements([new, duplicate, conflict])
    assert w.snapshot() == before


def test_f1_later_duplicate_at_retention_limit_is_still_a_noop():
    m = api()
    w = m.ReportWorkspace()
    rows = [f1_measurement(m, source_id=str(i)) for i in range(10000)]
    w.add_measurements(rows)
    before = w.snapshot()
    w.add_measurements([dataclasses.replace(rows[0], ingested_at=START + timedelta(seconds=2))])
    assert w.snapshot() == before


def test_f1_blood_pressure_secondary_remains_part_of_source_identity():
    m = api()
    w = m.ReportWorkspace()
    original = f1_measurement(m, metric="blood_pressure", unit="mmHg", value=120, value_secondary=80)
    w.add_measurements([original])
    before = w.snapshot()
    with pytest.raises(ValueError, match="Conflicting"):
        w.add_measurements([dataclasses.replace(original, value_secondary=81, ingested_at=START + timedelta(seconds=2))])
    assert w.snapshot() == before
