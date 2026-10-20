"""Camera-independent check-ins and separate numeric reflection reports."""
import csv
import hashlib
import io
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import uuid4

import pandas as pd
import streamlit as st

from stresslens.session_report import ReportWorkspace, SegmentConfig, SelfReport, to_export, to_text
from stresslens.session_measurements import (
    COLUMNS, MAX_BYTES, UNITS, ImportPreview, parse_measurements_csv, preview_measurements, validate_measurement,
)
from stresslens.output_summaries import report_overview

RESPONSES = [None, "0 · None", "1 · Low", "2 · High", "Unsure", "Skip"]
MEASURES = {"heart_rate": "Heart rate · bpm", "hrv_sdnn": "HRV SDNN · ms", "blood_pressure": "Blood pressure · mmHg"}


def utc_now():
    return datetime.now(UTC)


def response_value(choice):
    if choice is None:
        raise ValueError("Choose a response, Unsure or Skip before saving.")
    if choice == "Unsure":
        return "unsure", None
    if choice == "Skip":
        return "skipped", None
    if choice not in RESPONSES:
        raise ValueError("Unknown check-in response")
    return "answered", int(choice[0])


class ReportUIController:
    """UI-only prompt timing; camera and immutable reports keep their ownership."""

    def __init__(self, workspace=None):
        self.clock = monotonic
        self.workspace = workspace if workspace is not None else ReportWorkspace(clock=self.clock)
        self._anchor = None
        self._active = None
        self.import_generation = 0
        self.on_point_saved = None  # Optional companion adapter; core records stay the source of truth.

    def camera_utc(self):
        # Called by LaptopCamera at its actual explicit Start anchor.
        self._anchor = utc_now()
        return self._anchor

    def camera_started(self, session, config):
        segment_id = self.workspace.snapshot().active_segment_id
        deadline = session.segment_deadline()
        if segment_id is not None and deadline is not None and self._anchor is not None:
            self._active = (segment_id, config, self._anchor, deadline[0] - config.deadline)

    def add_point(self, choice):
        state, value = response_value(choice)
        self.workspace.add_self_report(SelfReport(str(uuid4()), utc_now(), state, value))
        if self.on_point_saved is not None:
            self.on_point_saved()

    def add_interval(self, prompt, choice):
        segment_id, start_utc, interval_end = prompt
        state, value = response_value(choice)
        self.workspace.add_self_report(SelfReport(
            str(uuid4()), utc_now(), state, value, "interval", segment_id,
            interval_end - 120, interval_end,
        ))

    def research_prompts(self):
        snapshot = self.workspace.snapshot()
        segments = [(s.segment_id, s.config, s.start_utc, s.duration_seconds) for s in snapshot.segments]
        if self._active is not None and snapshot.active_segment_id == self._active[0]:
            segment_id, config, start_utc, start_mono = self._active
            segments.append((segment_id, config, start_utc, min(config.deadline, max(0, self.clock() - start_mono))))
        answered = {(r.segment_id, r.interval_end) for r in snapshot.self_reports if r.scope == "interval"}
        pending = []
        now = utc_now()
        for segment_id, config, start_utc, duration in segments:
            if config.checkin_mode != "research":
                continue
            for end in range(120, int(duration) + 1, 120):
                if (segment_id, end) in answered:
                    continue
                due = start_utc + timedelta(seconds=end)
                if now > due + timedelta(seconds=30):
                    self.workspace.add_self_report(SelfReport(
                        str(uuid4()), now, "expired", scope="interval", segment_id=segment_id,
                        interval_start=end - 120, interval_end=end,
                    ))
                elif now >= due:
                    pending.append((segment_id, start_utc, end))
        return pending

    def reset(self):
        self._anchor = self._active = None
        self.import_generation += 1  # A new uploader widget drops the previous browser-file selection.


def ensure_report_controller():
    if "report_controller" not in st.session_state:
        st.session_state.report_controller = ReportUIController(st.session_state.get("report_workspace"))
    controller = st.session_state.report_controller
    st.session_state.report_workspace = controller.workspace
    return controller


def render_segment_options(disabled):
    activity = st.selectbox("Activity", ["other", "study", "work", "gaming", "call"],
                            key="report_activity", disabled=disabled)
    timer = st.selectbox("Optional camera timer", ["Until I stop", "10 minutes", "20 minutes", "Custom seconds"],
                         key="report_timer", disabled=disabled)
    seconds = None
    if timer == "Custom seconds":
        seconds = int(st.number_input("Camera timer in seconds", min_value=1, max_value=3600, value=60,
                                      step=1, key="report_custom_seconds", disabled=disabled))
    elif timer != "Until I stop":
        seconds = 600 if timer == "10 minutes" else 1200
    mode = st.selectbox("Check-in mode", ["Everyday", "Research · 2-minute intervals"],
                        key="report_checkin_mode", disabled=disabled)
    st.caption("Until I stop is the default. Engineering limits: 60 minutes per segment, 10 retained segments, "
               "and 1,000 check-ins. These are resource limits, not recommended observation times. "
               "Export and clear before reaching a retention limit.")
    st.caption("Everyday has no recurring prompts. Research offers optional two-minute interval questions "
               "that expire after 30 seconds. Camera off cancels future intervals.")
    return SegmentConfig(seconds, activity, "research" if mode.startswith("Research") else "everyday")


def _notice(message, kind="success"):
    st.session_state.report_notice = (kind, message)


def _save_point(controller):
    try:
        controller.add_point(st.session_state.get("report_point_response"))
    except (ValueError, RuntimeError) as exc:
        _notice(str(exc), "warning")
    else:
        st.session_state.report_point_response = None
        _notice("Current check-in saved at its answer time. It does not label a whole session.")


def _save_interval(controller, prompt, key):
    try:
        controller.add_interval(prompt, st.session_state.get(key))
    except (ValueError, RuntimeError) as exc:
        _notice(str(exc), "warning")
    else:
        _notice("Interval answer saved separately from facial observations.")


def _clear_report(controller, session, camera, explainer):
    try:
        if camera.running and not getattr(camera, "stopping", False):
            camera.stop(reason="user_off")
        if camera.running or not getattr(camera, "release_confirmed", not camera.running):
            _notice("Waiting for confirmed camera release. Report data has been retained.", "warning")
            return
        camera.clear_report()
        controller.workspace.clear()
    except (ValueError, RuntimeError) as exc:
        _notice(f"Report retained: {exc}", "warning")
        return
    controller.reset()
    explainer.reset()
    for key in list(st.session_state):
        if key.startswith("report_") and key not in {"report_workspace", "report_controller"}:
            del st.session_state[key]
    _notice("Report cleared. Camera is off. Earlier downloads are still on your computer.")


def render_checkins(controller):
    st.subheader("Your stress check-ins")
    st.caption("Optional start, end or any-time check-in. Camera and face-feature consent are not required. "
               "This simple scale is not a validated clinical instrument.")
    with st.form("report_point_form"):
        st.write("**How stressed do you feel right now?**")
        st.selectbox("Current stress", RESPONSES, format_func=lambda x: "Choose a response" if x is None else x,
                     key="report_point_response")
        st.form_submit_button("Add stress check-in", on_click=_save_point, args=(controller,))
    try:
        prompts = controller.research_prompts()
    except (ValueError, RuntimeError) as exc:
        st.warning(f"Check-in limit: {exc}")
        prompts = []
    for prompt in prompts:
        segment_id, start_utc, end = prompt
        key = f"report_interval_{segment_id}_{end}"
        with st.form(key + "_form"):
            st.write("**Thinking about the last two minutes, how stressed did you feel?**")
            st.caption(f"Segment {segment_id[:8]}, seconds {end - 120}–{end}. "
                       f"Answer by {(start_utc + timedelta(seconds=end + 30)).isoformat()} (UTC).")
            st.selectbox("Interval stress", RESPONSES, format_func=lambda x: "Choose a response" if x is None else x,
                         key=key)
            st.form_submit_button("Save interval answer", on_click=_save_interval, args=(controller, prompt, key))
    if st.session_state.get("report_notice"):
        kind, message = st.session_state.report_notice
        getattr(st, kind)(message)


def export_bundle(snapshot, include_measurements=False):
    """Both downloads use the same immutable revision and filtering choice."""
    return (json.dumps(to_export(snapshot, include_measurements), ensure_ascii=False, allow_nan=False, indent=2),
            to_text(snapshot, include_measurements))


@dataclass(frozen=True)
class PendingImport:
    fingerprint: str
    report_id: str | None
    revision: int
    preview: ImportPreview
    duplicates: int


def _reading_identity(row):
    return tuple(getattr(row, field) for field in COLUMNS)


def _measurement_table(rows):
    return pd.DataFrame([{
        "Time UTC": r.timestamp.isoformat(), "Measure": r.metric, "Value": r.value,
        "Secondary": r.value_secondary, "Unit": r.unit, "Device": r.device, "Method": r.method,
        "Source ID": r.source_id, "Ingested UTC": r.ingested_at.isoformat(),
        "Camera segment": r.segment_id or "Camera off",
    } for r in rows])


def _import_fingerprint(source):
    raw = source["raw"]
    identity = {**source, "raw": hashlib.sha256(raw).hexdigest() if raw is not None else None}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def _validated_import(source, snapshot):
    if source["file_error"]:
        raise ValueError(source["file_error"])
    if source["mode"] == "CSV file":
        if source["raw"] is None:
            raise ValueError("Choose a UTF-8 CSV file before previewing.")
        rows = parse_measurements_csv(source["raw"], ingested_at=utc_now())
        # Parsing already validated the CSV and collapsed identical rows. Count
        # its original nonempty records only; do not duplicate its validator.
        records = list(csv.reader(io.StringIO(source["raw"].decode("utf-8-sig"), newline="")))
        duplicates = sum(bool(row) for row in records[1:]) - len(rows)
    else:
        rows = [validate_measurement(source["row"], ingested_at=utc_now())]
        duplicates = 0
    preview = preview_measurements(rows, source["start"], source["end"], snapshot.segments)
    existing = {row.source_id: row for row in snapshot.measurements}
    new_count = 0
    for row in preview.included:
        if row.source_id in existing:
            if _reading_identity(row) != _reading_identity(existing[row.source_id]):
                raise ValueError("Conflicting measurement source ID; report retained.")
            duplicates += 1
        else:
            new_count += 1
    if len(existing) + new_count > 10000:
        raise ValueError("10000 measurements maximum; export/clear before adding. Report retained.")
    return preview, duplicates + preview.duplicate_count


def _import_allowed(snapshot, camera):
    return (snapshot.active_segment_id is None and not camera.running and
            not getattr(camera, "stopping", False) and getattr(camera, "release_confirmed", False))


def _commit_import(controller, camera, source, pending):
    before = controller.workspace.snapshot()
    if not _import_allowed(before, camera):
        raise ValueError("Add readings only after camera release is confirmed.")
    if (pending is None or pending.fingerprint != _import_fingerprint(source) or
            (pending.report_id, pending.revision) != (before.report_id, before.revision)):
        raise ValueError("Inputs, range or report changed. Preview readings again before adding.")
    preview, _ = _validated_import(source, before)
    latest = controller.workspace.snapshot()
    if not _import_allowed(latest, camera) or (latest.report_id, latest.revision) != (before.report_id, before.revision):
        raise ValueError("Report or camera changed. Preview readings again before adding.")
    if not preview.included:
        raise ValueError("No readings are selected by this range.")
    controller.workspace.add_measurements(preview.included)  # Existing locked API owns atomic cap/conflict/dedup.
    return len(controller.workspace.snapshot().measurements) - len(before.measurements)


def render_measurement_import(controller, camera):
    snapshot = controller.workspace.snapshot()
    allowed = _import_allowed(snapshot, camera)
    # Clearing server-side state alone can leave browser widgets cached inside
    # a fragment. A fresh identity resets every import control, not just files.
    suffix = f"_{controller.import_generation}" if controller.import_generation else ""
    def field_key(name):
        return f"report_import_{name}{suffix}"
    start_key, end_key = field_key("start"), field_key("end")
    with st.expander("Optional device readings · manual or CSV"):
        st.caption("A watch is not required. Add only readings you choose to supply; no device or account is accessed. "
                   "HR, device-reported SDNN and paired BP are separate observations, never stress labels. "
                   "Provenance is user supplied, not clinically verified.")
        mode = st.radio("Reading input", ["Manual entry", "CSV file"], key=field_key("mode"), disabled=not allowed)
        row, raw, file_error = {}, None, ""
        if mode == "Manual entry":
            row["timestamp"] = st.text_input("Measurement time (ISO 8601 with offset)", key=field_key("timestamp"), disabled=not allowed)
            row["metric"] = st.selectbox("Measure", list(MEASURES), format_func=MEASURES.get,
                                         key=field_key("metric"), disabled=not allowed)
            row["unit"] = UNITS[row["metric"]]
            st.caption(f"Unit: {row['unit']}. No unit conversion. SDNN is not RMSSD; BP requires a paired reading.")
            row["value"] = st.text_input("Value", key=field_key("value"), disabled=not allowed)
            row["value_secondary"] = st.text_input("Secondary value (BP diastolic only)", key=field_key("secondary"), disabled=not allowed)
            for field, label in [("device", "Device"), ("method", "Method"), ("source_id", "Stable source ID")]:
                row[field] = st.text_input(label, max_chars=120, key=field_key(field), disabled=not allowed)
        else:
            st.caption("UTF-8 CSV only; at most 1 MiB / 10,000 data rows. Exact columns:")
            st.code(",".join(COLUMNS), language=None)
            upload = st.file_uploader("Normalized readings CSV", type=["csv"], max_upload_size=1,
                                      key=f"report_import_file_{controller.import_generation}", disabled=not allowed)
            if upload is not None:
                if upload.size > MAX_BYTES:
                    file_error = "CSV exceeds the 1 MiB limit. No readings were added."
                else:
                    raw = upload.getvalue()
        if snapshot.segments and not st.session_state.get("report_import_seeded"):
            if not st.session_state.get(start_key) and not st.session_state.get(end_key):
                st.session_state[start_key] = min(s.start_utc for s in snapshot.segments).isoformat()
                st.session_state[end_key] = max(s.end_utc for s in snapshot.segments).isoformat()
            st.session_state.report_import_seeded = True
        st.caption("Choose the inclusive measurement range. Times need an explicit offset, for example +00:00. "
                   "Without facial segments, enter both endpoints; the range is never expanded automatically.")
        begin = st.text_input("Range start (ISO 8601 with offset)", key=start_key, disabled=not allowed)
        end = st.text_input("Range end (ISO 8601 with offset)", key=end_key, disabled=not allowed)
        source = {"mode": mode, "row": row, "raw": raw, "file_error": file_error, "start": begin, "end": end}
        st.session_state.report_import_dirty = bool(any(row.get(k) for k in COLUMNS if k not in {"metric", "unit"}) or
                                                    raw is not None or file_error or begin or end)
        if not allowed:
            st.caption("Preview and Add are available only with camera OFF and release confirmed.")
        if st.button("Preview readings", key="report_import_preview", disabled=not allowed):
            st.session_state.pop("report_import_pending", None)
            try:
                preview, duplicates = _validated_import(source, snapshot)
                st.session_state.report_import_pending = PendingImport(
                    _import_fingerprint(source), snapshot.report_id, snapshot.revision, preview, duplicates)
            except (ValueError, RuntimeError) as exc:
                st.warning(str(exc))
        pending = st.session_state.get("report_import_pending")
        current = (pending is not None and pending.fingerprint == _import_fingerprint(source) and
                   (pending.report_id, pending.revision) == (snapshot.report_id, snapshot.revision))
        if pending is not None:
            if current:
                preview = pending.preview
                st.write(f"Selected: {preview.included_count} · Excluded: {preview.excluded_count} · Duplicates: {pending.duplicates}")
                st.caption("Duplicates include identical input rows and readings already retained; they will not be added twice.")
                st.caption(f"Camera on: {preview.camera_on_count} · Camera off: {preview.camera_off_count}. " + preview.alignment_notice)
                if preview.included:
                    st.write("Selected readings")
                    st.dataframe(_measurement_table(preview.included), hide_index=True, width="stretch")
                if preview.excluded:
                    st.write("Excluded readings — outside the selected range")
                    st.dataframe(_measurement_table(preview.excluded), hide_index=True, width="stretch")
            else:
                st.warning("Inputs, range or report changed. Preview readings again before adding.")
        if st.button("Add to report", key="report_import_add", disabled=(
                not allowed or not current or not pending.preview.included_count)):
            try:
                added = _commit_import(controller, camera, source, pending)
            except (ValueError, RuntimeError) as exc:
                st.warning(str(exc))
            else:
                st.session_state.pop("report_import_pending", None)
                _notice(f"Added {added} new readings. Device data stays excluded from downloads unless you choose to include it.")
                st.rerun()  # Remove the consumed preview/Add action immediately.


def render_session_report(snapshot, *, camera_off=True):
    st.subheader("Your session report")
    st.write(report_overview(snapshot))
    st.caption("All times below are UTC. Facial movement and your answers remain separate.")
    if snapshot.report_id is None:
        st.caption("No observations or check-ins yet. You can add a check-in with the camera off.")
        return
    if snapshot.active_segment_id is not None or not camera_off:
        # Read completed observations directly; never disguise active data as
        # an exportable snapshot. Open tails have no proven off-camera end.
        expected = sum(s.expected_slots for s in snapshot.segments)
        valid = sum(s.valid_slots for s in snapshot.segments)
        summary = {
            "camera_on_seconds": sum(s.duration_seconds for s in snapshot.segments),
            "span_seconds": None, "expected_slots": expected, "valid_slots": valid,
            "coverage": valid / expected if expected else 0.0,
            "usable_windows": sum(w.usable for s in snapshot.segments for w in s.facial_windows),
        }
        gaps = [{"start_utc": left.end_utc.isoformat(), "end_utc": right.start_utc.isoformat(),
                 "duration_seconds": (right.start_utc - left.end_utc).total_seconds()}
                for left, right in zip(snapshot.segments, snapshot.segments[1:])
                if left.end_utc < right.start_utc]
        st.caption("Camera totals below cover finalized observations only. Report span and open gaps are pending "
                   "while capture is active or release is unconfirmed. Only gaps between finalized observations are shown.")
    else:
        payload = to_export(snapshot, include_measurements=bool(snapshot.measurements))
        summary, gaps = payload["session"], payload["off_camera_periods"]
    duration, span, coverage = st.columns(3)
    duration.metric("Camera-on duration", f"{summary['camera_on_seconds']:g} s")
    span.metric("Report span", "Pending" if summary["span_seconds"] is None else f"{summary['span_seconds']:g} s")
    coverage.metric("Usable camera slots", f"{summary['valid_slots']} / {summary['expected_slots']}")
    st.caption(f"Coverage {summary['coverage']:.0%}; {summary['usable_windows']} usable 20-second or partial windows. "
               "Provisional quality rule: at least 80% valid slots and longest missing run at most 2 seconds. "
               "Camera-off gaps are excluded from coverage.")
    details = st.expander("More details · session report", expanded=False)
    if snapshot.segments:
        with details:
            st.dataframe(pd.DataFrame([{
                "Segment": s.segment_id[:8], "Activity": s.config.activity, "Start UTC": s.start_utc.isoformat(),
                "End UTC": s.end_utc.isoformat(), "Seconds": s.duration_seconds,
                "Timer seconds": s.config.timer_seconds, "Stop reason": s.reason,
                "Complete": s.complete, "Coverage": s.coverage, "Max missing seconds": s.max_gap_seconds,
                "Samples/s": s.sampling_hz, "Reference captured": s.reference is not None,
            } for s in snapshot.segments]), hide_index=True, width="stretch")
    for gap in gaps:
        with details:
            st.write(f"Camera off — no facial observations: {gap['start_utc']} to {gap['end_utc']} "
                     f"({gap['duration_seconds']:g} seconds).")
    for segment in snapshot.segments:
        with st.container(border=True):
            st.markdown(f"**Facial movement · {segment.config.activity} · {segment.segment_id[:8]}**")
            if not segment.complete:
                st.write("Interrupted observation: capture ended before an ordinary stop or timer completion.")
            st.caption("Movement coefficients, not inferred stress or emotions. "
                       "An expression reference is optional and never establishes calmness.")
            if segment.duration_seconds == 0:
                st.write("Zero-duration observation: no movement summary.")
            elif segment.brief:
                st.write("Brief observation: duration and quality only; no trend conclusion.")
            if not any(w.usable for w in segment.facial_windows):
                st.write("Not enough usable camera data")
            windows = [{
                "Start UTC": (segment.start_utc + timedelta(seconds=w.start_seconds)).isoformat(),
                "End UTC": (segment.start_utc + timedelta(seconds=w.end_seconds)).isoformat(),
                "Start seconds": w.start_seconds, "End seconds": w.end_seconds,
                "Valid / expected": f"{w.valid_slots} / {w.expected_slots}", "Usable": w.usable,
                "Max missing seconds": w.max_gap_seconds, "Missing reasons": dict(w.reason_counts),
            } for w in segment.facial_windows]
            if windows:
                with details:
                    st.caption(f"Window quality · {segment.segment_id[:8]}")
                    st.dataframe(pd.DataFrame(windows), hide_index=True, width="stretch")
            if not segment.brief:
                rows = [{"Time UTC": (segment.start_utc + timedelta(seconds=w.start_seconds)).isoformat(),
                         "Feature": f.name, "Mean coefficient": f.mean}
                        for w in segment.facial_windows for f in w.features]
                if rows:
                    with details:
                        st.caption(f"Window means · {segment.segment_id[:8]}")
                        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                if segment.trend_available:
                    st.vega_lite_chart(pd.DataFrame(rows), spec={
                        "mark": {"type": "line", "point": True, "invalid": "break-paths-show-domains"},
                        "encoding": {"x": {"field": "Time UTC", "type": "temporal"},
                                     "y": {"field": "Mean coefficient", "type": "quantitative"},
                                     "color": {"field": "Feature", "type": "nominal"}},
                    }, width="stretch", height=200)
                    st.caption("Window means within this segment only. Missing windows break lines. "
                               "No line bridges camera-off periods.")
    st.markdown("**Your reported stress — separate from facial movement**")
    counts = Counter(r.state for r in snapshot.self_reports)
    st.write(" · ".join(f"{name}: {counts[name]}" for name in ("answered", "unsure", "skipped", "expired")))
    if snapshot.self_reports:
        with details:
            st.dataframe(pd.DataFrame([{
                "Answer time UTC": r.answered_at.isoformat(), "Response": r.state,
                "Value (0 None / 1 Low / 2 High)": r.value, "Scope": r.scope,
                "Segment": r.segment_id or "Camera off", "Interval start seconds": r.interval_start,
                "Interval end seconds": r.interval_end,
            } for r in snapshot.self_reports]), hide_index=True, width="stretch")
    else:
        st.caption("No stress answers supplied. Missing answers are not zero.")
    if snapshot.measurements:
        st.markdown("**Added device readings — user supplied**")
        for metric, label in MEASURES.items():
            rows = [r for r in snapshot.measurements if r.metric == metric]
            if rows:
                with details:
                    st.write(label)
                    st.dataframe(_measurement_table(rows), hide_index=True, width="stretch")
        st.caption("Separate timestamped observations; no interpolation, diagnosis or combined stress score.")
    else:
        st.caption("No device readings added. A watch is not needed to use this report.")
    if not camera_off or snapshot.active_segment_id is not None:
        st.caption("Downloads are available after camera release is confirmed.")
        return
    with details:
        include = st.checkbox("Include added device readings in downloads", value=False,
                              key="report_export_measurements", disabled=not snapshot.measurements)
        json_data, text_data = export_bundle(snapshot, include)
        left, right = st.columns(2)
        left.download_button("Download session JSON", json_data, file_name="stresslens-session.json",
                              mime="application/json", key="report_download_json")
        right.download_button("Download session TXT", text_data, file_name="stresslens-session.txt",
                               mime="text/plain", key="report_download_txt")


def render_report_panel(controller, session, camera, explainer):
    render_checkins(controller)
    render_measurement_import(controller, camera)
    render_session_report(controller.workspace.snapshot(), camera_off=(
        not camera.running and getattr(camera, "release_confirmed", not camera.running)))
    pending = getattr(camera, "stopping", False) or (not camera.running and not getattr(camera, "release_confirmed", True))
    st.button("Clear report", disabled=pending or (controller.workspace.snapshot().report_id is None and
                                                  not st.session_state.get("report_import_dirty", False)),
              on_click=_clear_report, args=(controller, session, camera, explainer), key="report_clear")
