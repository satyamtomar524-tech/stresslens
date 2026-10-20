"""Voluntary camera-free work sessions; history writes require explicit opt-in."""
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from stresslens.session_report import SelfReport
from stresslens.session_ui import RESPONSES, response_value
from stresslens.wellbeing import WorkSession, checkin_record
from stresslens.wellbeing_store import HistoryError, default_history_path, merge_checkins, save_history
from stresslens.output_summaries import work_overview


CLARITY_CHOICES = [None, "Clear", "Mixed", "Foggy", "Unsure", "Skip"]


@dataclass
class CompanionState:
    work: WorkSession = field(default_factory=WorkSession)
    history_path: Path = field(default_factory=default_history_path)
    form_token: str = field(default_factory=lambda: str(uuid4()))
    form_generation: int = 0
    extras: dict = field(default_factory=dict)
    restored: list = field(default_factory=list)
    history_enabled: bool = False
    history_error: str = ""
    history_dirty: bool = False
    notice: tuple | None = None
    report_id: str | None = None


def current_records(controller, state):
    records = []
    for point in controller.workspace.snapshot().self_reports:
        if point.scope == "point":
            context = state.extras.get(point.response_id, {})
            records.append(checkin_record(point, session_id=context.get("session_id", "standalone"),
                                          clarity=context.get("clarity", "skipped")))
    return merge_checkins([], records)


def persist_history(controller, state):
    if not state.history_enabled:
        return
    try:
        state.restored = save_history(state.history_path, current_records(controller, state))
    except HistoryError as exc:
        state.history_error, state.history_dirty = str(exc), True
    else:
        state.history_error, state.history_dirty = "", False


def toggle_history(controller, state):
    state.history_enabled = bool(st.session_state.get("wellbeing_keep_history", False))
    if state.history_enabled:
        persist_history(controller, state)
    else:
        state.restored, state.history_error, state.history_dirty = [], "", False


def save_checkin(state, controller, expected_token):
    if expected_token != state.form_token:
        return False
    generation = state.form_generation
    try:
        stress_state, stress_value = response_value(st.session_state.get(f"wellbeing_stress_{generation}"))
        choice = st.session_state.get(f"wellbeing_clarity_{generation}")
        if choice not in CLARITY_CHOICES:
            raise ValueError("Choose a listed clarity response or leave it unanswered.")
        clarity = "skipped" if choice in (None, "Skip") else choice.lower()
        session_id = state.work.session_id if state.work.state in {"working", "paused"} else "standalone"
        point = SelfReport(expected_token, state.work.utc_clock(), stress_state, stress_value)
        controller.workspace.add_self_report(point)
    except (ValueError, RuntimeError) as exc:
        state.notice = ("warning", str(exc))
        return False
    state.extras[point.response_id] = {"session_id": session_id, "clarity": clarity}
    state.form_generation += 1
    state.form_token = str(uuid4())
    state.notice = ("success", "Check-in saved in this app session at its answer time. It does not rate the unattended period.")
    persist_history(controller, state)
    return True


def synchronize_report(controller, state):
    snapshot = controller.workspace.snapshot()
    point_ids = {point.response_id for point in snapshot.self_reports if point.scope == "point"}
    state.extras = {identifier: context for identifier, context in state.extras.items() if identifier in point_ids}
    reset = state.report_id is not None and state.report_id != snapshot.report_id
    if reset:
        state.form_generation += 1
        state.form_token = str(uuid4())
        state.notice = None
    state.report_id = snapshot.report_id
    return reset


def render_wellbeing(controller, *, summarize):
    if "wellbeing_state" not in st.session_state:
        st.session_state.wellbeing_state = CompanionState()
    state = st.session_state.wellbeing_state
    synchronize_report(controller, state)
    controller.on_point_saved = lambda: persist_history(controller, state)
    work = state.work
    st.subheader("Your work session")
    st.caption("This work clock and your voluntary answers work with the camera off. "
               "Starting work never starts the camera or estimates stress.")
    with st.container(key="wellbeing_actions"):
        start, pause, resume, end = st.columns(4)
        start.button("Start work", disabled=work.state in {"working", "paused"}, type="primary",
                     on_click=work.start, key="wellbeing_start", width="stretch")
        pause.button("Pause work", disabled=work.state != "working", on_click=work.pause,
                     key="wellbeing_pause", width="stretch")
        resume.button("Resume work", disabled=work.state != "paused", on_click=work.resume,
                      key="wellbeing_resume", width="stretch")
        end.button("End work", disabled=work.state not in {"working", "paused"}, on_click=work.end,
                   key="wellbeing_end", width="stretch")
    enabled = st.checkbox("Show in-app break reminders", value=False, key="wellbeing_reminders")
    minutes = st.number_input("Break interval (minutes)", min_value=1, max_value=180, value=30,
                              step=1, disabled=not enabled, key="wellbeing_break_minutes")
    work.configure_reminders(enabled, int(minutes) * 60)
    st.caption("30 minutes is an adjustable preference, not medical advice. Prompts appear in this open app only; "
               "closed-tab or OS notifications are not provided. Pause or End stops active work time. "
               "Pausing starts a fresh reminder interval after Resume.")

    @st.fragment(run_every=1 if work.state == "working" else None)
    def work_status():
        status, elapsed = st.columns(2)
        status.metric("Work state", {"idle": "Not started", "working": "Working", "paused": "Paused", "ended": "Ended"}[work.state])
        seconds = int(work.elapsed_seconds)
        elapsed.metric("Active work time", f"{seconds // 60}m {seconds % 60:02d}s")
        prompt = work.due_prompt()
        if prompt is not None:
            st.info("Your chosen break interval is due. You can pause, snooze or dismiss it.")
            for column, label, action in zip(st.columns(3), ("Take break", "Snooze 5 minutes", "Dismiss"),
                                              ("take_break", "snooze", "dismiss"), strict=True):
                if column.button(label, key=f"wellbeing_prompt_{prompt.prompt_id}_{action}", width="stretch"):
                    if work.answer_reminder(prompt.prompt_id, action):
                        st.rerun()

    work_status()
    st.subheader("Check in now")
    st.caption("The same None / Low / High / Unsure / Skip stress scale is used in the session report. "
               "Clarity is an optional answer about now; leaving it blank is recorded as skipped.")
    generation = state.form_generation
    with st.form(f"wellbeing_checkin_{generation}"):
        st.selectbox("How stressed do you feel right now?", RESPONSES, index=0,
                     format_func=lambda value: "Choose a response" if value is None else value,
                     key=f"wellbeing_stress_{generation}")
        st.selectbox("How clear does your thinking feel right now? (optional)", CLARITY_CHOICES, index=0,
                     format_func=lambda value: "Leave unanswered" if value is None else value,
                     key=f"wellbeing_clarity_{generation}")
        st.form_submit_button("Save check-in", on_click=save_checkin, args=(state, controller, state.form_token))
    if state.notice:
        kind, message = state.notice
        getattr(st, kind)(message)

    @st.fragment(run_every=1)
    def history_and_patterns():
        # The existing point form can rerun only its own fragment. Read the shared ledger here.
        if synchronize_report(controller, state):
            st.rerun()  # Rebuild pending form identities after an explicit shared-report Clear.
        st.checkbox("Keep my check-in history on this laptop", value=False, key="wellbeing_keep_history",
                    on_change=toggle_history, args=(controller, state))
        st.caption(f"Optional history file: {state.history_path}. It contains only check-in IDs, times, work-session IDs, "
                   "stress choices and clarity choices. It saves current and future check-ins while enabled; "
                   "no images, free text or device readings. Restoring history never resumes work or camera capture.")
        if not state.history_enabled:
            st.caption("History saving is off. Answers stay in this app session; any earlier local history file remains on your laptop.")
        if state.history_enabled and not state.history_error:
            try:
                current = current_records(controller, state)
                saved_ids = {row["id"] for row in state.restored}
                if any(row["id"] not in saved_ids for row in current):
                    persist_history(controller, state)  # Explicit points from either existing form share history.
            except HistoryError as exc:
                state.history_error, state.history_dirty = str(exc), True
        if state.history_error:
            st.error(state.history_error)
            st.caption("Your new answers remain in this app session. The history file was not overwritten.")
        if state.history_enabled and state.history_dirty:
            st.button("Retry saving history", on_click=persist_history, args=(controller, state), key="wellbeing_retry_history")
    
        st.subheader("Your check-in patterns")
        st.caption("Counts describe answers you recorded, with missing choices kept separate. "
                   "They do not estimate stress automatically or show that a break caused a change.")
        try:
            current = current_records(controller, state)
            records = merge_checkins(state.restored if state.history_enabled else [], current)
            summary = summarize(records)
        except (ValueError, RuntimeError) as exc:
            st.warning(f"Check-in counts are unavailable: {exc}")
            return
        count, days = st.columns(2)
        count.metric("Recorded check-ins", summary["total_checkins"])
        days.metric("Days with check-ins (UTC)", summary["days_with_checkins"])
        st.write(work_overview(work.state, work.elapsed_seconds, summary))
        if summary["by_day"]:
            stress_table = pd.DataFrame([{"UTC date": row["date"], "Check-ins": row["checkin_count"], **row["stress_counts"]}
                                         for row in summary["by_day"]])
            clarity_table = pd.DataFrame([{"UTC date": row["date"], "Check-ins": row["checkin_count"], **row["clarity_counts"]}
                                          for row in summary["by_day"]])
            st.write("**Stress answers by UTC day**")
            st.bar_chart(stress_table.drop(columns="Check-ins").set_index("UTC date").rename(columns=str.title), height=220)
            st.write("**Clarity answers by UTC day**")
            st.bar_chart(clarity_table.drop(columns="Check-ins").set_index("UTC date").rename(columns=str.title), height=220)
            st.caption("Counts of recorded choices, including Unsure and missing choices; no stress estimate or imputed answers.")
            with st.expander("More details · check-in counts", expanded=False):
                st.dataframe(stress_table, hide_index=True, width="stretch")
                st.dataframe(clarity_table, hide_index=True, width="stretch")
        else:
            st.caption("No daily counts to display yet. Save a check-in to begin.")
        st.caption("Clearing the camera session report removes its current check-ins; a separately saved history file is retained.")

    history_and_patterns()
