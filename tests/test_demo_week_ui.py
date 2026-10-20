"""Fictional-week presentation must never operate on a person's session."""
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from stresslens.session_report import Measurement, SelfReport
from stresslens.wellbeing import WorkSession
from stresslens.wellbeing_ui import CompanionState


ROOT = Path(__file__).resolve().parents[1]


def button(app, label):
    return next(item for item in app.button if item.label == label)


def shown(app):
    return "\n".join(item.value for kind in ("caption", "markdown", "info", "warning", "error")
                     for item in getattr(app, kind))


@pytest.fixture
def real_session(tmp_path):
    clock = SimpleNamespace(value=100.0)
    state = CompanionState(work=WorkSession(clock=lambda: clock.value),
                           history_path=tmp_path / "private" / "history.json")
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.session_state["wellbeing_state"] = state
    app.run()
    assert not app.exception
    workspace = app.session_state["report_workspace"]
    stamp = datetime(2026, 10, 18, 8, tzinfo=UTC)
    workspace.add_self_report(SelfReport("personal-fixture-point", stamp, "answered", 2))
    workspace.add_measurements([Measurement("personal-fixture-72", stamp, "heart_rate", 72, "bpm",
                                            "Fictional device", "Manual practice", stamp)])
    app.run()
    app.checkbox(key="wellbeing_keep_history").check().run()
    app.checkbox(key="wellbeing_reminders").check().run()
    app.number_input(key="wellbeing_break_minutes").set_value(45).run()
    button(app, "Start work").click().run()
    clock.value = 160.0
    return SimpleNamespace(app=app, state=state, clock=clock, workspace=workspace)


def test_demo_round_trips_preserve_active_clock_report_and_history_preferences(real_session, monkeypatch):
    real = real_session
    before = real.workspace.snapshot()
    original_bytes = real.state.history_path.read_bytes()
    session_id = real.state.work.session_id

    def forbidden(*args, **kwargs):
        raise AssertionError("The fictional view must not read/write personal history or add a real point")

    for _ in range(2):
        with monkeypatch.context() as isolated:
            isolated.setattr("stresslens.wellbeing_ui.save_history", forbidden)
            isolated.setattr("stresslens.wellbeing_store.load_history", forbidden)
            isolated.setattr(type(real.workspace), "add_self_report", forbidden)
            button(real.app, "Explore a fictional week").click().run()
            for _ in range(2):
                real.app.run()
            assert not real.app.exception
            assert real.app.query_params["example"] == "fictional-week"
            assert "Fictional example — not your data" in shown(real.app)
            assert not real.app.checkbox and not real.app.download_button
            assert real.workspace.snapshot() == before
            assert real.state.history_path.read_bytes() == original_bytes
            assert real.state.work.state == "working"
            assert real.state.work.session_id == session_id and real.state.work.elapsed_seconds == 60
        button(real.app, "Return to my session").click().run()
        assert not real.app.exception and "example" not in real.app.query_params
        assert real.app.checkbox(key="wellbeing_keep_history").value
        assert real.app.checkbox(key="wellbeing_reminders").value
        assert real.app.number_input(key="wellbeing_break_minutes").value == 45
        assert real.workspace.snapshot() == before and real.state.history_path.read_bytes() == original_bytes
        assert real.state.work.session_id == session_id and real.state.work.state == "working"
        assert not real.app.session_state["laptop_camera"].running
        assert not real.app.checkbox(key="face_sdk_metrics_opt_in").value


def test_cold_demo_url_renders_no_personal_services_and_stays_labelled_on_rerun(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Cold fictional URL must not initialize or restore a personal session")
    monkeypatch.setattr("stresslens.live_ui.render_live_camera", forbidden)
    monkeypatch.setattr("stresslens.wellbeing_ui.render_wellbeing", forbidden)
    monkeypatch.setattr("stresslens.session_ui.ensure_report_controller", forbidden)
    monkeypatch.setattr("stresslens.wellbeing_store.load_history", forbidden)
    monkeypatch.setattr("stresslens.wellbeing_store.save_history", forbidden)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.query_params["example"] = "fictional-week"
    app.run()
    app.run()
    assert not app.exception
    assert "Fictional example — not your data" in shown(app)
    assert "report_workspace" not in app.session_state and "wellbeing_state" not in app.session_state
    assert not app.checkbox and not app.download_button and not list(tmp_path.iterdir())
    assert {item.label: item.value for item in app.metric} == {"Example check-ins": "14", "Example days": "7"}
    assert len(app.table) == 2
    stress, clarity = [table.value for table in app.table]
    assert stress["Check-ins"].tolist() == [2, 2, 2, 2, 2, 2, 2]
    assert stress[["None", "Low", "High", "Unsure", "Skipped", "Expired"]].sum().tolist() == [3, 3, 4, 2, 2, 0]
    assert clarity[["Clear", "Mixed", "Foggy", "Unsure", "Skipped"]].sum().tolist() == [3, 3, 3, 3, 2]
    assert "Answered stress: 10/14" in shown(app) and "Clarity supplied: 9/14" in shown(app)
    assert button(app, "Return to my session")


def test_fictional_exact_counts_use_static_tables_without_download_controls():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    app.query_params["example"] = "fictional-week"
    app.run()
    assert not app.exception
    assert not app.download_button and not app.dataframe
    assert len(app.table) == 2
    assert not app.get("vega_lite_chart")
