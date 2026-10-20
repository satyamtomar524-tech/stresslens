"""Actual Streamlit companion UI with fictional points, clock and private temp path."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from stresslens.wellbeing import WorkSession
from stresslens.session_report import SelfReport
from stresslens.wellbeing_ui import CompanionState, save_checkin


PAGE = '''
import streamlit as st
from stresslens.session_ui import ensure_report_controller
from stresslens.wellbeing_ui import render_wellbeing
from stresslens.personal_patterns import summarize_checkins
def summary_spy(records):
    st.session_state["summary_input"] = records
    return summarize_checkins(records)
render_wellbeing(ensure_report_controller(), summarize=summary_spy)
'''


def button(app, label):
    return next(item for item in app.button if item.label == label)


def shown(app):
    return "\n".join(item.value for kind in ("caption", "markdown", "info", "success", "warning", "error")
                     for item in getattr(app, kind))


@pytest.fixture
def ui(tmp_path):
    clock = SimpleNamespace(value=0.0)
    anchor = datetime(2026, 10, 18, 9, tzinfo=UTC)
    state = CompanionState(work=WorkSession(clock=lambda: clock.value,
                                           utc_clock=lambda: anchor + timedelta(seconds=clock.value)),
                           history_path=tmp_path / "private" / "history.json")
    app = AppTest.from_string(PAGE, default_timeout=10)
    app.session_state["wellbeing_state"] = state
    app.run()
    assert not app.exception
    return SimpleNamespace(app=app, state=state, clock=clock)


def answer(ui, stress="0 · None", clarity=None):
    generation = ui.state.form_generation
    ui.app.selectbox(key=f"wellbeing_stress_{generation}").set_value(stress)
    if clarity is not None:
        ui.app.selectbox(key=f"wellbeing_clarity_{generation}").set_value(clarity)
    button(ui.app, "Save check-in").click().run()
    assert not ui.app.exception


def test_work_reminders_and_local_history_start_off(ui):
    assert ui.state.work.state == "idle"
    assert not ui.app.checkbox(key="wellbeing_reminders").value
    assert not ui.app.checkbox(key="wellbeing_keep_history").value
    assert ui.app.selectbox(key="wellbeing_stress_0").value is None
    assert ui.app.selectbox(key="wellbeing_clarity_0").value is None
    assert not ui.state.history_path.exists() and not ui.state.history_path.parent.exists()
    assert not ui.app.session_state["report_workspace"].snapshot().self_reports


def test_work_clock_controls_do_not_create_ratings(ui):
    button(ui.app, "Start work").click().run()
    ui.clock.value = 90
    button(ui.app, "Pause work").click().run()
    ui.clock.value = 600
    ui.app.run()
    assert ui.state.work.elapsed_seconds == 90
    button(ui.app, "Resume work").click().run()
    ui.clock.value = 620
    button(ui.app, "End work").click().run()
    assert ui.state.work.state == "ended" and ui.state.work.elapsed_seconds == 110
    assert not ui.app.session_state["report_workspace"].snapshot().self_reports


def test_explicit_answer_uses_shared_point_record_once_and_optional_clarity(ui):
    button(ui.app, "Start work").click().run()
    old_token = ui.state.form_token
    answer(ui, clarity="Mixed")
    points = ui.app.session_state["report_workspace"].snapshot().self_reports
    assert len(points) == 1 and (points[0].state, points[0].value, points[0].scope) == ("answered", 0, "point")
    assert ui.app.session_state["summary_input"][0]["clarity"] == "mixed"
    assert ui.app.session_state["summary_input"][0]["session_id"] == ui.state.work.session_id
    for _ in range(3):
        ui.app.run()
    assert len(ui.app.session_state["report_workspace"].snapshot().self_reports) == 1
    assert not save_checkin(ui.state, ui.app.session_state["report_controller"], old_token)
    assert ui.app.selectbox(key="wellbeing_stress_1").value is None
    assert ui.app.selectbox(key="wellbeing_clarity_1").value is None
    assert not ui.state.history_path.exists()


@pytest.mark.parametrize("choice,state", [("Unsure", "unsure"), ("Skip", "skipped")])
def test_missing_answers_and_unanswered_clarity_stay_missing(ui, choice, state):
    answer(ui, stress=choice)
    record = ui.app.session_state["summary_input"][0]
    assert record["stress_state"] == state and record["stress_value"] is None
    assert record["clarity"] == "skipped" and record["session_id"] == "standalone"


def test_empty_submit_does_not_create_an_answer(ui):
    button(ui.app, "Save check-in").click().run()
    assert not ui.app.exception
    assert not ui.app.session_state["report_workspace"].snapshot().self_reports
    assert "Choose a response" in shown(ui.app)


def test_one_due_prompt_on_return_snooze_and_take_break(ui):
    ui.app.checkbox(key="wellbeing_reminders").check().run()
    ui.app.number_input(key="wellbeing_break_minutes").set_value(1).run()
    button(ui.app, "Start work").click().run()
    ui.clock.value = 3600
    ui.app.run()
    token = ui.state.work.due_prompt().prompt_id
    ui.app.run()
    assert ui.state.work.due_prompt().prompt_id == token
    assert len([item for item in ui.app.button if item.label == "Take break"]) == 1
    button(ui.app, "Snooze 5 minutes").click().run()
    assert ui.state.work.due_prompt() is None
    ui.clock.value += 300
    ui.app.run()
    button(ui.app, "Take break").click().run()
    elapsed = ui.state.work.elapsed_seconds
    assert ui.state.work.state == "paused"
    ui.clock.value += 3600
    ui.app.run()
    assert ui.state.work.elapsed_seconds == elapsed and ui.state.work.due_prompt() is None


def test_history_opt_in_restores_only_records_never_running_timers(ui):
    button(ui.app, "Start work").click().run()
    answer(ui)
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    assert ui.state.history_path.exists() and len(ui.state.restored) == 1
    fresh = CompanionState(history_path=ui.state.history_path)
    app = AppTest.from_string(PAGE)
    app.session_state["wellbeing_state"] = fresh
    app.run()
    assert not fresh.restored and not app.checkbox(key="wellbeing_keep_history").value
    app.checkbox(key="wellbeing_keep_history").check().run()
    assert len(fresh.restored) == 1
    assert fresh.work.state == "idle" and not fresh.work.reminders_enabled
    assert not app.session_state["report_workspace"].snapshot().self_reports
    app.checkbox(key="wellbeing_keep_history").uncheck().run()
    assert not fresh.restored and ui.state.history_path.exists()


def test_malformed_history_is_visible_and_new_answer_remains_in_memory(ui):
    ui.state.history_path.parent.mkdir()
    ui.state.history_path.write_bytes(b"fictional malformed history")
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    assert "malformed" in shown(ui.app)
    answer(ui, stress="1 · Low", clarity="Foggy")
    assert ui.state.history_path.read_bytes() == b"fictional malformed history"
    assert len(ui.app.session_state["report_workspace"].snapshot().self_reports) == 1
    assert "malformed" in shown(ui.app)


def test_existing_point_form_shares_history_without_duplicate_writes(ui, monkeypatch):
    import stresslens.wellbeing_ui as view
    calls = []
    original = view.save_history
    def save_spy(path, records):
        calls.append(len(records))
        return original(path, records)
    monkeypatch.setattr(view, "save_history", save_spy)
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    point = SelfReport("fictional-legacy-point", datetime(2026, 10, 18, 10, tzinfo=UTC), "answered", 2)
    ui.app.session_state["report_workspace"].add_self_report(point)
    ui.app.run()
    assert len(ui.state.restored) == 1
    assert ui.state.restored[0]["clarity"] == "skipped"
    assert ui.state.restored[0]["id"] == point.response_id
    count = len(calls)
    ui.app.run()
    assert len(calls) == count


def test_real_patterns_function_counts_cross_day_history_and_missing_answers(ui):
    from stresslens.wellbeing_store import save_history
    save_history(ui.state.history_path, [
        {"id": "fictional-day1", "answered_at": "2026-10-18T08:00:00Z", "session_id": "fictional-work",
         "stress_state": "answered", "stress_value": 0, "clarity": "clear"},
        {"id": "fictional-day2", "answered_at": "2026-10-18T23:30:00-02:00", "session_id": "fictional-work",
         "stress_state": "answered", "stress_value": 2, "clarity": "foggy"},
    ])
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    answer(ui, stress="Unsure")
    metrics = {item.label: item.value for item in ui.app.metric}
    assert metrics["Recorded check-ins"] == "3" and metrics["Days with check-ins (UTC)"] == "2"
    stress, clarity = [frame.value for frame in ui.app.dataframe]
    assert list(stress["UTC date"]) == ["2026-10-18", "2026-10-19"]
    assert list(stress["unsure"]) == [1, 0] and list(stress["high"]) == [0, 1]
    assert list(clarity["skipped"]) == [1, 0]
    assert "automatically" in shown(ui.app) and "caused" in shown(ui.app)


def test_later_malformed_history_is_visible_on_first_new_shared_point_render(ui):
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    ui.state.history_path.write_bytes(b"fictional later corruption")
    point = SelfReport("fictional-later-point", datetime(2026, 10, 18, 10, tzinfo=UTC), "unsure")
    ui.app.session_state["report_workspace"].add_self_report(point)
    ui.app.run()
    assert not ui.app.exception
    assert "malformed" in shown(ui.app)
    assert ui.state.history_path.read_bytes() == b"fictional later corruption"


def test_clearing_shared_report_drops_current_clarity_and_pending_form_not_work_clock(ui):
    button(ui.app, "Start work").click().run()
    answer(ui, clarity="Foggy")
    previous_generation = ui.state.form_generation
    assert ui.state.extras
    ui.app.session_state["report_workspace"].clear()
    ui.app.run()
    assert not ui.state.extras and not ui.app.session_state["summary_input"]
    assert ui.state.form_generation > previous_generation
    assert ui.app.selectbox(key=f"wellbeing_stress_{ui.state.form_generation}").value is None
    assert ui.app.selectbox(key=f"wellbeing_clarity_{ui.state.form_generation}").value is None
    assert ui.state.work.state == "working" and not ui.state.history_path.exists()


def test_existing_point_api_saves_opted_in_history_before_a_later_render(ui):
    ui.app.checkbox(key="wellbeing_keep_history").check().run()
    ui.app.session_state["report_controller"].add_point("2 · High")
    assert len(ui.state.restored) == 1
    assert ui.state.restored[0]["stress_value"] == 2 and ui.state.restored[0]["clarity"] == "skipped"
