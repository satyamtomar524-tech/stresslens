"""Actual Streamlit component, synthetic clock/camera/numeric data only."""
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from stresslens.session_report import FEATURE_LABELS, Measurement

PAGE = "from stresslens.live_ui import render_live_camera\nrender_live_camera()"
ANCHOR = datetime(2026, 10, 16, 12, tzinfo=UTC)


def t4_manual(ui, **changes):
    app = ui.app
    assert any(item.label == "Preview readings" for item in app.button), "Optional measurement preview UI missing"
    values = {"timestamp": ANCHOR.isoformat(), "value": "70", "secondary": "",
              "device": "Fictional device", "method": "Synthetic fixture", "source_id": "manual-1",
              "start": ANCHOR.isoformat(), "end": (ANCHOR + timedelta(seconds=20)).isoformat()}
    values.update(changes)
    for key, value in values.items():
        app.text_input(key="report_import_" + key).set_value(value)
    return app


def t4_csv(ui, body):
    app = t4_manual(ui)
    app.radio(key="report_import_mode").set_value("CSV file").run()
    readings_file(app).set_value(("FICTIONAL_READINGS.csv", body, "text/csv")).run()
    return app


def readings_file(app):
    return next(item for item in app.file_uploader if item.label == "Normalized readings CSV")


T4_HEADER = "timestamp,metric,value,value_secondary,unit,device,method,source_id\n"
T4_CSV = (T4_HEADER +
          "2026-10-16T12:00:00Z,heart_rate,70,,bpm,Fictional,Synthetic,csv-hr\n" * 2 +
          "2026-10-16T12:00:10Z,hrv_sdnn,35,,ms,Fictional,Synthetic,csv-sdnn\n" +
          "2026-10-16T12:00:30Z,blood_pressure,120,80,mmHg,Fictional cuff,Synthetic,csv-bp\n").encode()


def test_t4_manual_preview_is_read_only_then_explicit_add_and_export_choices(ui):
    app = t4_manual(ui)
    before = app.session_state["report_workspace"].snapshot()
    button(app, "Preview readings").click().run()
    assert not app.exception and app.session_state["report_workspace"].snapshot() == before
    assert "Selected: 1" in text(app) and "Device clocks may differ" in text(app)
    app.run()
    assert app.session_state["report_workspace"].snapshot() == before
    button(app, "Add to report").click().run()
    snapshot = app.session_state["report_workspace"].snapshot()
    assert not app.exception and len(snapshot.measurements) == 1
    assert "Added 1 new readings" in text(app)
    record = snapshot.measurements[0]
    assert (record.source_id, record.value, record.unit, record.segment_id) == ("manual-1", 70, "bpm", None)
    assert record.timestamp == ANCHOR and record.ingested_at == ANCHOR
    assert "measurements" not in json.loads(ui.downloads["Download session JSON"])
    assert button(app, "Add to report").disabled
    app.checkbox(key="report_export_measurements").check().run()
    included = json.loads(ui.downloads["Download session JSON"])
    included_txt = ui.downloads["Download session TXT"]
    assert included["measurements"][0]["source_id"] == "manual-1"
    assert included == json.loads(ui.downloads["Download session TXT"].split("retained):\n", 1)[1])
    app.checkbox(key="report_export_measurements").uncheck().run()
    assert "measurements" not in json.loads(ui.downloads["Download session JSON"])
    print("T4_EXPORT " + json.dumps({"json": included, "txt": included_txt}))


def test_t4_csv_range_dedup_and_separate_units_without_preview_writes(ui):
    app = t4_csv(ui, T4_CSV)
    workspace = app.session_state["report_workspace"]
    button(app, "Preview readings").click().run()
    assert workspace.snapshot().report_id is None
    assert "Selected: 2" in text(app) and "Excluded: 1" in text(app) and "Duplicates: 1" in text(app)
    button(app, "Add to report").click().run()
    saved = workspace.snapshot()
    assert [(r.source_id, r.value, r.unit) for r in saved.measurements] == [("csv-hr", 70, "bpm"), ("csv-sdnn", 35, "ms")]
    assert not app.exception and "Heart rate · bpm" in text(app) and "HRV SDNN · ms" in text(app)
    button(app, "Preview readings").click().run()
    assert "Duplicates: 3" in text(app)
    button(app, "Add to report").click().run()
    assert workspace.snapshot() == saved  # A repeat changes neither records nor revision/ingestion.


@pytest.mark.parametrize("changes", [{"start": ""}, {"start": "2026-10-16T12:00:00"},
                                     {"start": "2026-10-17T00:00:00Z"}, {"value": "NaN"},
                                     {"timestamp": "unknown"}, {"device": ""}])
def test_t4_manual_rejects_invalid_range_or_source_atomically(ui, changes):
    app = t4_manual(ui, **changes)
    before = app.session_state["report_workspace"].snapshot()
    button(app, "Preview readings").click().run()
    assert not app.exception and app.warning
    assert button(app, "Add to report").disabled
    assert app.session_state["report_workspace"].snapshot() == before


@pytest.mark.parametrize("body,reason", [(b"timestamp,value\nwrong,NaN\n", "header"),
                                         (T4_CSV.replace(b",ms,", b",RMSSD,"), "unit"), (b"\xff", "UTF-8"),
                                         (b"x" * (1024 * 1024 + 1), "1 MiB"),
                                         ((T4_HEADER + "2026-10-16T12:00:00Z,heart_rate,70,,bpm,Fictional,Synthetic,same\n" * 10001).encode(), "10000")],
                         ids=["bad-header", "wrong-unit", "invalid-utf8", "over-1mib", "over-10000-rows"])
def test_t4_malformed_csv_does_not_mutate_workspace(ui, body, reason):
    app = t4_csv(ui, body)
    before = app.session_state["report_workspace"].snapshot()
    button(app, "Preview readings").click().run()
    assert not app.exception and app.warning and button(app, "Add to report").disabled
    assert reason in text(app)
    assert app.session_state["report_workspace"].snapshot() == before


@pytest.mark.parametrize("changed", ["source", "range", "revision"])
def test_t4_stale_preview_cannot_commit(ui, changed):
    app = t4_manual(ui)
    button(app, "Preview readings").click().run()
    workspace = app.session_state["report_workspace"]
    if changed == "revision":
        app.selectbox(key="report_point_response").set_value("0 · None")
        button(app, "Add stress check-in").click().run()
    else:
        app.text_input(key="report_import_" + ("value" if changed == "source" else "end")).set_value(
            "71" if changed == "source" else "2026-10-16T12:00:15Z").run()
    before = workspace.snapshot()
    assert button(app, "Add to report").disabled and "changed" in text(app).lower()
    app.run()
    assert workspace.snapshot() == before and not before.measurements


def test_t4_csv_conflict_preserves_existing_and_new_rows_atomically(ui):
    app = t4_manual(ui)
    button(app, "Preview readings").click().run()
    button(app, "Add to report").click().run()
    workspace = app.session_state["report_workspace"]
    before = workspace.snapshot()
    body = (T4_HEADER + "2026-10-16T12:00:01Z,heart_rate,72,,bpm,Fictional,Synthetic,new\n" +
            "2026-10-16T12:00:00Z,heart_rate,71,,bpm,Fictional device,Synthetic fixture,manual-1\n").encode()
    app = t4_csv(ui, body)
    button(app, "Preview readings").click().run()
    if not button(app, "Add to report").disabled:
        button(app, "Add to report").click().run()
    assert not app.exception and "conflict" in text(app).lower()
    assert workspace.snapshot() == before


def test_t4_cumulative_cap_rejection_preserves_all_records(ui):
    workspace = ui.app.session_state["report_workspace"]
    workspace.add_measurements([Measurement(f"cap-{i}", ANCHOR, "heart_rate", 70, "bpm",
                                          "Fictional", "Synthetic", ANCHOR) for i in range(10000)])
    before = workspace.snapshot()
    ui.app.run()
    app = t4_manual(ui)
    button(app, "Preview readings").click().run()
    if not button(app, "Add to report").disabled:
        button(app, "Add to report").click().run()
    assert not app.exception and "10000" in text(app)
    assert workspace.snapshot() == before


@pytest.mark.parametrize("pending", [False, True])
def test_t4_camera_active_or_unreleased_blocks_import(ui, pending):
    app = t4_manual(ui)
    button(app, "Preview readings").click().run()
    camera = start(ui)
    if pending:
        camera.pending_release = True
        ui.clock.value = 1
        button(app, "Stop camera").click().run()
    assert button(app, "Preview readings").disabled and button(app, "Add to report").disabled
    assert not app.session_state["report_workspace"].snapshot().measurements


def test_t4_clear_resets_pending_input_file_export_and_preserves_no_device_flow(ui):
    app = t4_csv(ui, T4_CSV)
    button(app, "Preview readings").click().run()
    assert not button(app, "Clear report").disabled  # Preview alone can be cleared without allocating a report ID.
    button(app, "Clear report").click().run()
    assert not app.exception and app.session_state["report_workspace"].snapshot().report_id is None
    assert next(x for x in app.text_input if x.label == "Range start (ISO 8601 with offset)").value == ""
    assert next(x for x in app.text_input if x.label == "Value").value == ""
    assert "report_import_pending" not in app.session_state
    mode = next(x for x in app.radio if x.label == "Reading input")
    assert mode.value == "Manual entry"
    mode.set_value("CSV file").run()
    assert readings_file(app).value is None
    assert "No device readings added" in text(app) or "No observations or check-ins" in text(app)
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value


def test_t4_manual_blood_pressure_retains_pair_and_provenance(ui):
    app = t4_manual(ui, value="120", secondary="80", source_id="fictional-bp")
    app.selectbox(key="report_import_metric").set_value("blood_pressure")
    button(app, "Preview readings").click().run()
    assert not app.exception and not app.session_state["report_workspace"].snapshot().measurements
    button(app, "Add to report").click().run()
    record = app.session_state["report_workspace"].snapshot().measurements[0]
    assert (record.metric, record.value, record.value_secondary, record.unit) == ("blood_pressure", 120, 80, "mmHg")
    assert record.device == "Fictional device" and record.method == "Synthetic fixture"
    assert "Blood pressure · mmHg" in text(app)


def test_t4_range_defaults_only_to_finalized_segments(ui):
    app = ui.app
    assert app.text_input(key="report_import_start").value == ""
    start(ui)
    ui.clock.value = 2
    button(app, "Stop camera").click().run()
    assert app.text_input(key="report_import_start").value == ANCHOR.isoformat()
    assert app.text_input(key="report_import_end").value == (ANCHOR + timedelta(seconds=2)).isoformat()


def test_t4_csv_widget_advertises_bounded_import_and_rejects_oversize(ui):
    app = t4_csv(ui, b"x" * (1024 * 1024 + 1))
    assert readings_file(app).proto.max_upload_size_mb == 1, "Upload advertises a larger file than the import accepts"
    before = app.session_state["report_workspace"].snapshot()
    button(app, "Preview readings").click().run()
    assert not app.exception and "1 MiB" in text(app)
    assert app.session_state["report_workspace"].snapshot() == before


def test_t4_clear_invalidates_import_widget_identities_for_browser_reset(ui):
    app = t4_manual(ui)
    button(app, "Preview readings").click().run()
    old_range = next(x.id for x in app.text_input if x.label == "Range start (ISO 8601 with offset)")
    old_mode = next(x.id for x in app.radio if x.label == "Reading input")
    button(app, "Clear report").click().run()
    field = next(x for x in app.text_input if x.label == "Range start (ISO 8601 with offset)")
    mode = next(x for x in app.radio if x.label == "Reading input")
    assert field.id != old_range and mode.id != old_mode, "Clear must invalidate cached browser input identities"
    assert field.value == "" and mode.value == "Manual entry"
    mode.set_value("CSV file").run()
    assert readings_file(app).value is None


def button(app, label):
    return next(item for item in app.button if item.label == label)


def text(app):
    return "\n".join(item.value for kind in ("caption", "markdown", "info", "warning", "success", "error")
                     for item in getattr(app, kind))


def test_session_ui_off_default_has_camera_free_checkin_without_sdk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No camera/SDK initialization during camera-off check-in")

    monkeypatch.setattr("stresslens.live._detector", forbidden)
    monkeypatch.setattr("stresslens.live.cv2.VideoCapture", forbidden)
    app = AppTest.from_string(PAGE).run()
    assert not app.exception
    assert any(item.label == "Add stress check-in" for item in app.button)
    assert button(app, "Start camera").disabled
    assert app.session_state["report_workspace"].snapshot().report_id is None
    app.selectbox(key="report_point_response").set_value("0 · None")
    assert app.selectbox(key="report_point_response").value == "0 · None"
    button(app, "Add stress check-in").click().run()
    assert not app.exception
    snapshot = app.session_state["report_workspace"].snapshot()
    assert snapshot.report_id and not snapshot.segments, {
        "notice": app.session_state["report_notice"],
        "same_workspace": app.session_state["report_controller"].workspace is app.session_state["report_workspace"],
        "messages": text(app),
    }
    assert snapshot.self_reports[0].value == 0 and snapshot.self_reports[0].segment_id is None
    assert not app.session_state["laptop_camera"].running
    assert len(app.get("download_button")) == 2


@pytest.fixture
def ui(monkeypatch):
    import stresslens.session_ui as session_ui

    clock = SimpleNamespace(value=0.0)
    def now():
        return clock.value
    monkeypatch.setattr(session_ui, "monotonic", now)
    monkeypatch.setattr(session_ui, "utc_now", lambda: ANCHOR + timedelta(seconds=clock.value))
    downloads = {}
    original_download = st.delta_generator.DeltaGenerator.download_button

    def capture_download(container, label, data, **kwargs):
        downloads[label] = data
        return original_download(container, label, data, **kwargs)

    monkeypatch.setattr(st.delta_generator.DeltaGenerator, "download_button", capture_download)

    class FakeCamera:
        def __init__(self, session, utc_clock=None):
            self.session, self.utc_clock = session, utc_clock
            self.running = self.stopping = self.pending_release = False
            self.release_confirmed = True
            self.reason = self.stopped_at = None

        def start(self, index=0, *, segment_config=None):
            if self.running:
                return
            assert self.release_confirmed
            self.session.begin_segment(segment_config, self.utc_clock(), now())
            self.running, self.release_confirmed = True, False

        def stop(self, reason="user_off"):
            self.reason, self.stopped_at = reason, now()
            self.session.finish_segment(reason, now())
            if self.pending_release:
                self.stopping = True
            else:
                self.session.stop(reason, now())
                self.running = self.stopping = False
                self.release_confirmed = True

        def complete_release(self):
            self.session.stop(self.reason, self.stopped_at)
            self.running = self.stopping = False
            self.release_confirmed = True

        def preview(self):
            return None, None

        def clear_report(self):
            assert not self.running and self.release_confirmed
            self.session.clear_report()

        def observations(self, duration, unavailable=None):
            segment = self.session._report_segment
            for slot in range(round(duration * 10)):
                groups = {} if unavailable else dict.fromkeys(FEATURE_LABELS, 0.25)
                segment.observe(slot / 10, groups, unavailable)

    monkeypatch.setattr("stresslens.live_ui.LaptopCamera", FakeCamera)
    app = AppTest.from_string(PAGE, default_timeout=10).run()
    assert not app.exception
    return SimpleNamespace(app=app, clock=clock, downloads=downloads)


def start(ui, *, timer="Until I stop", mode="Everyday", seconds=None):
    app = ui.app
    app.checkbox(key="face_sdk_metrics_opt_in").check().run()
    app.selectbox(key="report_timer").set_value(timer).run()
    if seconds is not None:
        app.number_input(key="report_custom_seconds").set_value(seconds).run()
    app.selectbox(key="report_checkin_mode").set_value(mode).run()
    button(app, "Start camera").click().run()
    assert not app.exception
    return app.session_state["laptop_camera"]


@pytest.mark.parametrize("response,state,value", [("0 · None", "answered", 0), ("Unsure", "unsure", None), ("Skip", "skipped", None)])
def test_point_answers_exports_and_reset_are_camera_independent(ui, response, state, value):
    app = ui.app
    button(app, "Add stress check-in").click().run()
    assert not app.exception and not app.session_state["report_workspace"].snapshot().self_reports
    app.selectbox(key="report_point_response").set_value(response)
    ui.clock.value = 2
    button(app, "Add stress check-in").click().run()
    record = app.session_state["report_workspace"].snapshot().self_reports[0]
    assert (record.state, record.value, record.segment_id) == (state, value, None)
    assert record.answered_at == ANCHOR + timedelta(seconds=2)
    payload = json.loads(ui.downloads["Download session JSON"])
    txt_payload = json.loads(ui.downloads["Download session TXT"].split("Report details (timestamps in UTC; separate units retained):\n", 1)[1])
    assert payload == txt_payload and payload["schema"] == "session-report/2"
    assert payload["self_reports"][0]["value"] == value and "measurements" not in payload
    first_id = payload["session"]["report_id"]
    button(app, "Clear report").click().run()
    assert not app.exception and not app.session_state["laptop_camera"].running
    assert app.session_state["report_workspace"].snapshot().report_id is None
    assert not app.get("download_button")
    assert app.selectbox(key="report_point_response").value is None
    assert app.selectbox(key="report_timer").value == "Until I stop"
    app.selectbox(key="report_point_response").set_value("1 · Low")
    button(app, "Add stress check-in").click().run()
    assert app.session_state["report_workspace"].snapshot().report_id != first_id


def test_on_off_on_retains_reports_gap_and_half_open_point_association(ui):
    camera = start(ui)
    app = ui.app
    assert button(app, "Start camera").disabled and not button(app, "Stop camera").disabled
    assert app.selectbox(key="report_timer").disabled and not app.get("download_button")
    camera.observations(1)
    ui.clock.value = 1
    button(app, "Stop camera").click().run()
    first = app.session_state["report_workspace"].snapshot().segments[0]
    app.selectbox(key="report_point_response").set_value("2 · High")
    button(app, "Add stress check-in").click().run()
    assert app.session_state["report_workspace"].snapshot().self_reports[0].segment_id is None
    ui.clock.value = 5
    button(app, "Start camera").click().run()
    camera.observations(2)
    ui.clock.value = 7
    button(app, "Stop camera").click().run()
    assert not app.exception
    snapshot = app.session_state["report_workspace"].snapshot()
    assert len(snapshot.segments) == 2 and snapshot.segments[0] is first
    assert snapshot.segments[0].segment_id != snapshot.segments[1].segment_id
    assert snapshot.segments[1].reference is None
    payload = json.loads(ui.downloads["Download session JSON"])
    assert payload["session"]["camera_on_seconds"] == 3 and payload["session"]["span_seconds"] == 7
    assert payload["off_camera_periods"][0]["duration_seconds"] == 4
    assert "Camera off — no facial observations" in text(app)
    assert "Brief observation" in text(app) and not app.get("vega_lite_chart")


@pytest.mark.parametrize("reason", ["no_face", "multiple_faces", "unsampled"])
def test_custom_timer_missing_data_remains_unavailable(ui, reason):
    camera = start(ui, timer="Custom seconds", seconds=2)
    if reason != "unsampled":
        camera.observations(2, unavailable=reason)
    ui.clock.value = 2
    camera.stop("timer_end")
    ui.app.run()
    assert not ui.app.exception
    report = ui.app.session_state["report_workspace"].snapshot().segments[0]
    assert (report.reason, report.duration_seconds, report.expected_slots, report.valid_slots) == ("timer_end", 2, 20, 0)
    assert "Not enough usable camera data" in text(ui.app)
    assert "Finalized camera-on time: 2 s" in text(ui.app)
    assert "no valid facial measurements" in text(ui.app)
    assert "2 s of facial movement" not in text(ui.app)
    exported = json.loads(ui.downloads["Download session JSON"])
    assert (exported["session"]["camera_on_seconds"], exported["session"]["valid_slots"],
            exported["session"]["expected_slots"]) == (2, 0, 20)
    assert not button(ui.app, "Start camera").disabled
    assert len(ui.app.get("download_button")) == 2


def test_pending_release_and_revocation_keep_report_and_block_unsafe_controls(ui):
    camera = start(ui)
    camera.pending_release = True
    ui.clock.value = 1
    ui.app.checkbox(key="face_sdk_metrics_opt_in").uncheck().run()
    app = ui.app
    assert not app.exception and camera.stopping and camera.reason == "consent_revoked"
    assert button(app, "Start camera").disabled and button(app, "Clear report").disabled
    assert button(app, "Stop camera").disabled and not app.get("download_button")
    assert app.session_state["report_workspace"].snapshot().segments[0].reason == "consent_revoked"
    app.selectbox(key="report_point_response").set_value("0 · None")
    button(app, "Add stress check-in").click().run()
    assert len(app.session_state["report_workspace"].snapshot().self_reports) == 1
    camera.complete_release()
    app.run()
    assert not button(app, "Clear report").disabled and len(app.get("download_button")) == 2
    assert button(app, "Start camera").disabled  # SDK choice remains revoked.
    button(app, "Clear report").click().run()
    assert not app.session_state["report_workspace"].snapshot().segments


def test_clear_requests_stop_before_reset_and_keeps_sdk_choice(ui):
    camera = start(ui)
    ui.clock.value = 1
    button(ui.app, "Clear report").click().run()
    assert not ui.app.exception and not camera.running and camera.release_confirmed
    assert ui.app.session_state["report_workspace"].snapshot().report_id is None
    assert ui.app.checkbox(key="face_sdk_metrics_opt_in").value
    assert not ui.app.get("download_button")


def test_research_prompt_after_off_expires_without_crossing_gap(ui):
    camera = start(ui, mode="Research · 2-minute intervals")
    ui.clock.value = 121
    button(ui.app, "Stop camera").click().run()
    app = ui.app
    assert "Thinking about the last two minutes" in text(app)
    app.selectbox(key=next(item.key for item in app.selectbox if item.key.startswith("report_interval_"))).set_value("1 · Low")
    button(app, "Save interval answer").click().run()
    record = app.session_state["report_workspace"].snapshot().self_reports[0]
    assert (record.scope, record.interval_start, record.interval_end, record.value) == ("interval", 0, 120, 1)
    assert record.answered_at == ANCHOR + timedelta(seconds=121)
    ui.clock.value = 500
    app.run()
    assert len(app.session_state["report_workspace"].snapshot().self_reports) == 1
    assert not camera.running and not any(item.label == "Save interval answer" for item in app.button)


def test_expired_research_answer_is_missing_and_everyday_has_no_prompts(ui):
    start(ui, mode="Research · 2-minute intervals")
    ui.clock.value = 151
    ui.app.run()
    records = ui.app.session_state["report_workspace"].snapshot().self_reports
    assert len(records) == 1 and records[0].state == "expired" and records[0].value is None
    assert not any(item.label == "Save interval answer" for item in ui.app.button)
    button(ui.app, "Stop camera").click().run()
    button(ui.app, "Clear report").click().run()
    start(ui)
    ui.clock.value = 400
    ui.app.run()
    assert not ui.app.session_state["report_workspace"].snapshot().self_reports


def test_device_export_choice_is_explicit_and_resets(ui):
    workspace = ui.app.session_state["report_workspace"]
    workspace.add_measurements([Measurement("synthetic-1", ANCHOR, "heart_rate", 70, "bpm",
                                             "synthetic device", "synthetic fixture", ANCHOR)])
    ui.app.run()
    assert "measurements" not in json.loads(ui.downloads["Download session JSON"])
    ui.app.checkbox(key="report_export_measurements").check().run()
    assert json.loads(ui.downloads["Download session JSON"])["measurements"][0]["source_id"] == "synthetic-1"
    button(ui.app, "Clear report").click().run()
    assert "report_export_measurements" not in ui.app.session_state


def test_report_chart_breaks_missing_window_and_keeps_table_alternative(ui):
    camera = start(ui)
    segment = camera.session._report_segment
    for slot in range(600):
        groups = {} if 200 <= slot < 400 else dict.fromkeys(FEATURE_LABELS, 0.25)
        segment.observe(slot / 10, groups, "no_face" if not groups else None)
    ui.clock.value = 60
    button(ui.app, "Stop camera").click().run()
    assert not ui.app.exception and len(ui.app.get("vega_lite_chart")) == 1
    assert len(ui.app.dataframe) >= 3
    payload = json.loads(ui.downloads["Download session JSON"])
    windows = payload["segments"][0]["facial_windows"]
    assert [w["usable"] for w in windows] == [True, False, True]
    assert windows[1]["features"][0]["mean"] is None
    assert "No line bridges camera-off periods" in text(ui.app)


def test_interval_answer_submitted_after_expiry_is_rejected(ui):
    start(ui, mode="Research · 2-minute intervals")
    ui.clock.value = 120
    ui.app.run()
    key = next(item.key for item in ui.app.selectbox if item.key.startswith("report_interval_"))
    ui.app.selectbox(key=key).set_value("2 · High")
    ui.clock.value = 151
    button(ui.app, "Save interval answer").click().run()
    assert not ui.app.exception
    answers = ui.app.session_state["report_workspace"].snapshot().self_reports
    assert len(answers) == 1 and answers[0].state == "expired" and answers[0].value is None


def test_clear_during_pending_stop_retains_data_until_another_explicit_clear(ui):
    camera = start(ui)
    camera.pending_release = True
    ui.clock.value = 1
    button(ui.app, "Clear report").click().run()
    assert not ui.app.exception and camera.stopping
    assert ui.app.session_state["report_workspace"].snapshot().report_id is not None
    assert button(ui.app, "Clear report").disabled
    camera.complete_release()
    ui.app.run()
    assert ui.app.session_state["report_workspace"].snapshot().report_id is not None
    button(ui.app, "Clear report").click().run()
    assert ui.app.session_state["report_workspace"].snapshot().report_id is None


@pytest.mark.parametrize("timer,seconds", [("10 minutes", 600), ("20 minutes", 1200)])
def test_optional_timer_presets_reach_backend_without_starting_by_selection(ui, timer, seconds):
    ui.app.selectbox(key="report_timer").set_value(timer).run()
    assert not ui.app.session_state["laptop_camera"].running
    camera = start(ui, timer=timer)
    assert camera.session.segment_deadline() == (seconds, "timer_end")
    ui.clock.value = 1
    button(ui.app, "Stop camera").click().run()


def f3_displayed_gap_ranges(app):
    prefix = "Camera off — no facial observations: "
    result = []
    for item in app.markdown:
        if item.value.startswith(prefix):
            bounds = item.value.removeprefix(prefix).split(" (", 1)[0]
            result.append(tuple(datetime.fromisoformat(t) for t in bounds.split(" to ")))
    return result


def f3_capture_view(ui, case, phase):
    """Selected -s runs save actual UI records, not simulated inspection flags."""
    app = ui.app
    snapshot = app.session_state["report_workspace"].snapshot()
    camera = app.session_state["laptop_camera"]
    record = {
        "case": case, "phase": phase, "fixture": "SYNTHETIC fake camera and clock; no capture/SDK",
        "clock_seconds": ui.clock.value, "fixture_origin_utc": ANCHOR.isoformat(),
        "camera_running": camera.running, "release_confirmed": camera.release_confirmed,
        "active_segment_id": snapshot.active_segment_id,
        "finalized_segments": [{"id": s.segment_id, "start_utc": s.start_utc.isoformat(),
                                "end_utc": s.end_utc.isoformat(), "duration": s.duration_seconds}
                               for s in snapshot.segments],
        "point_answers": len(snapshot.self_reports),
        "gap_text": [m.value for m in app.markdown if m.value.startswith("Camera off — no facial observations:")],
        "download_controls": len(app.get("download_button")),
    }
    if record["download_controls"]:
        record["json_export"] = json.loads(ui.downloads["Download session JSON"])
        record["txt_export"] = ui.downloads["Download session TXT"]
    print("F3_VIEW " + json.dumps(record))


@pytest.mark.parametrize("with_point", [False, True], ids=["no-point", "point-at-25"])
def test_f3_active_restart_never_labels_active_capture_camera_off(ui, with_point):
    camera = start(ui)
    app = ui.app
    camera.observations(10)
    ui.clock.value = 10
    button(app, "Stop camera").click().run()
    first = app.session_state["report_workspace"].snapshot().segments[0]
    ui.clock.value = 20
    button(app, "Start camera").click().run()
    second_id = app.session_state["report_workspace"].snapshot().active_segment_id
    ui.clock.value = 25
    if with_point:
        app.selectbox(key="report_point_response").set_value("1 · Low")
        button(app, "Add stress check-in").click().run()
    else:
        app.run()
    assert not app.exception
    f3_capture_view(ui, f"restart-{with_point}", "active")
    snapshot = app.session_state["report_workspace"].snapshot()
    assert snapshot.segments == (first,) and snapshot.segments[0] is first
    assert snapshot.active_segment_id == second_id and camera.running
    assert not app.get("download_button")
    assert all(end <= ANCHOR + timedelta(seconds=20) for _, end in f3_displayed_gap_ranges(app)), text(app)
    ui.clock.value = 30
    button(app, "Stop camera").click().run()
    assert not app.exception
    f3_capture_view(ui, f"restart-{with_point}", "after-stop")
    snapshot = app.session_state["report_workspace"].snapshot()
    assert snapshot.segments[0] is first and snapshot.segments[1].segment_id == second_id
    payload = json.loads(ui.downloads["Download session JSON"])
    txt = json.loads(ui.downloads["Download session TXT"].split("Report details (timestamps in UTC; separate units retained):\n", 1)[1])
    assert payload == txt and payload["schema"] == "session-report/2"
    assert [(g["start_utc"], g["end_utc"], g["duration_seconds"]) for g in payload["off_camera_periods"]] == [
        ((ANCHOR + timedelta(seconds=10)).isoformat(), (ANCHOR + timedelta(seconds=20)).isoformat(), 10)]
    assert payload["session"]["camera_on_seconds"] == 20 and payload["session"]["span_seconds"] == 30
    assert len(payload["self_reports"]) == int(with_point)


@pytest.mark.parametrize("point_count", [0, 1, 2])
def test_f3_first_active_segment_has_no_invented_off_gap(ui, point_count):
    camera = start(ui)
    app = ui.app
    active_id = app.session_state["report_workspace"].snapshot().active_segment_id
    for index in range(point_count):
        ui.clock.value = index + 1
        app.selectbox(key="report_point_response").set_value("0 · None")
        button(app, "Add stress check-in").click().run()
    ui.clock.value = 2
    app.run()
    assert not app.exception
    f3_capture_view(ui, f"first-active-{point_count}", "active")
    assert camera.running and app.session_state["report_workspace"].snapshot().active_segment_id == active_id
    assert not app.get("download_button")
    assert not f3_displayed_gap_ranges(app), text(app)
    ui.clock.value = 3
    button(app, "Stop camera").click().run()
    assert not app.exception
    f3_capture_view(ui, f"first-active-{point_count}", "after-stop")
    payload = json.loads(ui.downloads["Download session JSON"])
    assert payload["off_camera_periods"] == [] and len(payload["self_reports"]) == point_count


def test_f3_checkin_only_off_report_keeps_real_off_gap(ui):
    app = ui.app
    for seconds, response in [(1, "0 · None"), (3, "2 · High")]:
        ui.clock.value = seconds
        app.selectbox(key="report_point_response").set_value(response)
        button(app, "Add stress check-in").click().run()
    assert not app.exception
    f3_capture_view(ui, "checkin-only", "camera-off")
    assert not app.session_state["laptop_camera"].running
    assert f3_displayed_gap_ranges(app) == [(ANCHOR + timedelta(seconds=1), ANCHOR + timedelta(seconds=3))]
    assert len(app.get("download_button")) == 2
    payload = json.loads(ui.downloads["Download session JSON"])
    assert payload["session"]["camera_on_seconds"] == 0 and payload["session"]["span_seconds"] == 2
    assert [r["value"] for r in payload["self_reports"]] == [0, 2]
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value


def test_f3_active_third_segment_retains_closed_gap_without_false_open_tail(ui):
    start(ui)
    app = ui.app
    ui.clock.value = 10
    button(app, "Stop camera").click().run()
    ui.clock.value = 20
    button(app, "Start camera").click().run()
    ui.clock.value = 30
    button(app, "Stop camera").click().run()
    first_two = app.session_state["report_workspace"].snapshot().segments
    ui.clock.value = 40
    button(app, "Start camera").click().run()
    ui.clock.value = 45
    app.selectbox(key="report_point_response").set_value("Unsure")
    button(app, "Add stress check-in").click().run()
    assert not app.exception
    f3_capture_view(ui, "third-active", "active")
    gaps = f3_displayed_gap_ranges(app)
    assert (ANCHOR + timedelta(seconds=10), ANCHOR + timedelta(seconds=20)) in gaps
    assert all(end <= ANCHOR + timedelta(seconds=40) for _, end in gaps), text(app)
    assert app.session_state["report_workspace"].snapshot().segments == first_two
    assert not app.get("download_button")
    ui.clock.value = 50
    button(app, "Stop camera").click().run()
    f3_capture_view(ui, "third-active", "after-stop")
    payload = json.loads(ui.downloads["Download session JSON"])
    assert [g["duration_seconds"] for g in payload["off_camera_periods"]] == [10, 10]
@pytest.mark.parametrize("status,age,title", [
    ("waiting", None, "Starting your session"),
    ("ok", 0.4, "Collecting facial movement"),
    ("ok", 3.1, "No usable facial observation"),
    ("no_face", 0.2, "No usable facial observation"),
    ("multiple_faces", 0.2, "No usable facial observation"),
    ("too_far", 0.2, "No usable facial observation"),
])
def test_return_status_distinguishes_current_stale_and_missing(ui, monkeypatch, status, age, title):
    camera = start(ui)
    ui.clock.value = age or 0
    monkeypatch.setattr(camera.session, "snapshot", lambda: {
        "status": status, "message": "Synthetic observation status",
        "groups": {"Eye narrowing": 0.6} if status == "ok" else {},
        "history": [], "frame_age_seconds": None if age is None else ui.clock.value,
        "measurement_fps": 8, "latency_ms": 12,
    })
    ui.app.run()
    assert not ui.app.exception
    shown = text(ui.app)
    assert title in shown
    if status == "ok" and age <= 2:
        assert "Last frame received 0.4 seconds ago" in shown
        assert any("Coefficient" in frame.value.columns for frame in ui.app.dataframe)
    else:
        assert "Collecting facial movement" not in shown
        assert not any("Coefficient" in frame.value.columns for frame in ui.app.dataframe)
    assert shown.count("Stored in this app session only") == 1
    assert "Last valid face at" not in shown


def test_return_status_explains_consent_and_session_only_history(ui):
    shown = text(ui.app)
    assert "Start unavailable: face features are off" in shown
    assert shown.count("Stored in this app session only") == 1
    assert "No finalized camera observations" in shown
    assert not ui.app.checkbox(key="face_sdk_metrics_opt_in").value


def test_return_status_keeps_inactivity_history_separate_from_new_capture(ui):
    camera = start(ui)
    camera.observations(1)
    ui.clock.value = 20
    camera.stop("inactivity")
    ui.app.run()
    shown = text(ui.app)
    assert "Camera is off" in shown
    assert "Paused after 20 seconds without page updates" in shown
    assert "Latest finalized camera observation (UTC)" in shown
    assert ANCHOR.isoformat() in shown
    assert (ANCHOR + timedelta(seconds=20)).isoformat() in shown
    assert "Stop reason: inactivity" in shown
    assert "Last valid face at" not in shown
    assert not button(ui.app, "Start camera").disabled
    first = ui.app.session_state["report_workspace"].snapshot().segments[0]
    ui.clock.value = 25
    button(ui.app, "Start camera").click().run()
    assert "Starting your session" in text(ui.app)
    assert "Latest finalized camera observation (UTC)" in text(ui.app)
    assert ui.app.session_state["report_workspace"].snapshot().segments[0] is first


@pytest.mark.parametrize("worker_running", [True, False])
def test_return_status_pending_release_is_never_camera_off_or_current(ui, worker_running):
    camera = start(ui)
    camera.pending_release = True
    ui.clock.value = 1
    camera.stop()
    camera.running = worker_running
    ui.app.run()
    shown = text(ui.app)
    assert "Finishing your session" in shown
    assert "Start unavailable: device release is unconfirmed" in shown
    assert "### Camera is off" not in shown
    assert "Collecting facial movement" not in shown
    assert shown.count("device release is unconfirmed") == 1
    assert button(ui.app, "Start camera").disabled
    assert button(ui.app, "Clear report").disabled
    assert not ui.app.get("download_button")


def test_return_status_current_frame_becomes_stale_without_stopping_capture(ui, monkeypatch):
    camera = start(ui)
    segment_id = ui.app.session_state["report_workspace"].snapshot().active_segment_id
    monkeypatch.setattr(camera.session, "snapshot", lambda: {
        "status": "ok", "groups": {"Eye narrowing": 0.6}, "history": [],
        "frame_age_seconds": ui.clock.value, "measurement_fps": 8,
    })
    ui.clock.value = 0.1
    ui.app.run()
    assert "Collecting facial movement" in text(ui.app)
    ui.clock.value = 2.1
    ui.app.run()
    assert "No usable facial observation" in text(ui.app)
    assert "last frame is stale" in text(ui.app)
    assert "Collecting facial movement" not in text(ui.app)
    assert camera.running
    assert ui.app.session_state["report_workspace"].snapshot().active_segment_id == segment_id


def test_return_status_capture_error_is_off_and_report_remains_historical(ui, monkeypatch):
    camera = start(ui)
    ui.clock.value = 2
    camera.stop("capture_error")
    monkeypatch.setattr(camera, "preview", lambda: (None, "Synthetic camera open failure"))
    ui.app.run()
    shown = text(ui.app)
    assert "Camera is off" in shown and "previous capture failed" in shown
    assert "Synthetic camera open failure" in shown
    assert "Stop reason: capture_error" in shown
    assert "Latest finalized camera observation (UTC)" in shown
    assert "Collecting facial movement" not in shown
    assert not button(ui.app, "Start camera").disabled
    assert len(ui.app.get("download_button")) == 2
