"""Literal count/score fixtures protect missing data and separate provenance."""
import importlib
from datetime import UTC, datetime

import pytest

from stresslens.session_report import FEATURE_LABELS, ReportWorkspace, SegmentConfig, SelfReport


def summaries():
    return importlib.import_module("stresslens.output_summaries")


def test_analysis_summary_keeps_zero_self_rating_separate_from_model_and_no_face():
    text = {"status": "ok", "stress_probability": 0.73}
    face = {"status": "no_face", "face_frames": 0, "frames_analyzed": 1}
    summary = summaries().analysis_overview(text, face, 0)
    assert "0/10" in summary and "your answer" in summary.lower()
    assert "stress-related language" in summary.lower()
    assert "0.73" not in summary and "uncalibrated" not in summary.lower()
    assert "no face" in summary.lower()
    assert "low stress" not in summary.lower() and "calm" not in summary.lower()


def test_text_only_primary_summary_uses_plain_source_bound_wording():
    summary = summaries().analysis_overview({"status": "ok", "stress_probability": 0.65, "label": "stress"}, None, None)
    assert summary == "Your text contains stress-related language. No self-rating or photo/video was included."


def test_analysis_summary_does_not_turn_missing_or_failed_inputs_into_zero_scores():
    summary = summaries().analysis_overview({"status": "insufficient"}, None, None)
    assert "not provided" in summary.lower() and "unavailable" in summary.lower()
    assert "0.00" not in summary and "0/10" not in summary


def test_failed_face_analysis_is_unavailable_instead_of_a_no_face_observation():
    summary = summaries().analysis_overview(None, {"status": "error", "face_frames": 0, "frames_analyzed": 0}, None)
    assert "unavailable" in summary.lower()
    assert "no face measured" not in summary.lower()


def test_work_summary_uses_actual_active_time_and_all_missing_categories():
    rows = {"total_checkins": 3, "days_with_checkins": 1, "by_day": [{
        "stress_counts": {"none": 1, "low": 0, "high": 0, "unsure": 1, "skipped": 1, "expired": 0},
        "clarity_counts": {"clear": 0, "mixed": 1, "foggy": 0, "unsure": 1, "skipped": 1},
    }]}
    summary = summaries().work_overview("paused", 95, rows)
    assert "Paused" in summary and "1m 35s" in summary
    assert "1/3" in summary and "2 missing" in summary
    assert "self-reported" in summary.lower() and "clarity" in summary.lower()


def test_empty_report_summary_never_claims_camera_measurements_or_stress():
    workspace = ReportWorkspace()
    summary = summaries().report_overview(workspace.snapshot())
    assert "0" in summary and "no camera" in summary.lower()
    workspace.add_self_report(SelfReport("fictional-skip", datetime(2026, 10, 19, tzinfo=UTC), "skipped"))
    summary = summaries().report_overview(workspace.snapshot())
    assert "0/1" in summary and "1 missing" in summary
    assert "no camera" in summary.lower()


def test_finalized_camera_summary_without_valid_samples():
    workspace = ReportWorkspace(clock=lambda: 20.0)
    workspace.start_segment(SegmentConfig(), datetime(2026, 10, 19, 17, tzinfo=UTC), 0.0)
    segment = workspace.finish_segment(20.0, "user_off")
    assert segment.duration_seconds == 20 and segment.expected_slots == 200 and segment.valid_slots == 0
    assert not any(window.usable for window in segment.facial_windows)
    before = workspace.snapshot()
    summary = summaries().report_overview(before)
    assert "Finalized camera-on time: 20 s" in summary
    assert "no valid facial measurements" in summary.lower()
    assert "20 s of facial movement" not in summary
    assert workspace.snapshot() == before


@pytest.mark.parametrize("samples,periodic_gaps,reason,coverage_phrase", [
    (50, False, "capture_error", "coverage is too limited"),
    (200, True, "user_off", "facial measurements have gaps"),
    (200, False, "capture_error", "facial measurements are available"),
])
def test_finalized_camera_summary_distinguishes_partial_and_interrupted_coverage(samples, periodic_gaps, reason, coverage_phrase):
    workspace = ReportWorkspace(clock=lambda: 20.0)
    accumulator = workspace.start_segment(SegmentConfig(), datetime(2026, 10, 19, 17, tzinfo=UTC), 0.0)
    for i in range(samples):
        if not periodic_gaps or i % 5 != 0:
            accumulator.observe(i / 10, {name: 0.25 for name in FEATURE_LABELS})
    segment = workspace.finish_segment(20.0, reason)
    assert segment.valid_slots == (160 if periodic_gaps else samples)
    assert any(window.usable for window in segment.facial_windows) is (samples == 200)
    summary = summaries().report_overview(workspace.snapshot())
    assert "Finalized camera-on time: 20 s" in summary
    assert coverage_phrase in summary
    assert ("interrupted" in summary) is (not segment.complete)
    assert "20 s of facial movement" not in summary
