"""Exercise the actual Streamlit UI, including local model integration."""

from pathlib import Path
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
ENGLISH_TEXT = (
    "I have been feeling overwhelmed by everything I need to finish this week. "
    "I keep worrying about the deadlines and I cannot relax or sleep properly. "
    "It feels like there is too much pressure on me right now."
)


@pytest.fixture
def app():
    result = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not result.exception
    return result


def own_inputs(app):
    app.tabs[1].radio[0].set_value("My inputs").run()
    assert not app.exception
    return app


def button(app, label):
    return next(item for item in app.button if item.label == label)


def metric_values(app):
    return {item.label: item.value for item in app.tabs[1].metric}


def messages(elements):
    return "\n".join(item.value for item in elements)


def upload_photo(app, name, data, mime="image/png"):
    next(item for item in app.tabs[1].file_uploader if item.label.startswith("Upload ")).set_value((name, data, mime)).run()


def media_permission(app):
    return next(item for item in app.tabs[1].checkbox if item.label.startswith("This is my"))


def enable_face_features(app):
    app.checkbox(key="face_sdk_metrics_opt_in").check().run()
    assert not app.exception
    return app


def test_face_features_require_google_metrics_opt_in_by_default(app):
    assert button(app, "Start camera").disabled
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value
    assert button(app, "Capture photo").disabled
    assert next(item for item in app.tabs[1].file_uploader if item.label == "Short video (optional)").disabled
    app.radio(key="analysis_input_choice").set_value("Fictional text example").run()
    assert not button(app, "Analyze example").disabled


def test_approved_navigation_and_privacy_disclosure_preserve_text_input(app):
    assert [tab.label for tab in app.tabs] == ["Live camera", "Upload & text", "Sources", "About", "Work session"]
    assert any(item.label == "Camera options" and not item.proto.expanded for item in app.tabs[0].expander)
    assert app.get("popover")[0].proto.popover.label == "Review camera privacy"
    own_inputs(app)
    app.text_area[0].set_value(ENGLISH_TEXT)
    button(app, "Analyze my inputs").click().run()
    enable_face_features(app)
    assert app.text_area[0].value == ENGLISH_TEXT
    assert not app.session_state["laptop_camera"].running
    app.checkbox(key="face_sdk_metrics_opt_in").uncheck().run()
    assert app.text_area[0].value == ENGLISH_TEXT
    assert button(app, "Start camera").disabled
    assert not button(app, "Analyze my inputs").disabled


@pytest.mark.parametrize("consented", [False, True])
def test_idle_camera_view_has_one_actionable_status_and_no_empty_insights(app, consented):
    if consented:
        enable_face_features(app)
    live = app.tabs[0]
    assert len(live.info) == 1
    assert "Research-informed insights" not in messages(live.subheader)
    if not consented:
        assert "Start unavailable: face features are off." in live.info[0].value
        assert "Press Start camera" not in messages(live.info)
        assert button(app, "Start camera").disabled
    else:
        assert "Start" in live.info[0].value
        assert not button(app, "Start camera").disabled


def test_existing_upload_is_blocked_when_google_metrics_opt_in_is_revoked(app, monkeypatch):
    def unexpected_inference(*args, **kwargs):
        raise AssertionError("Face inference must not run before opt-in.")

    monkeypatch.setattr("stresslens.face.analyze_image", unexpected_inference)
    monkeypatch.setattr("stresslens.face.analyze_video", unexpected_inference)
    enable_face_features(app)
    own_inputs(app)
    output = io.BytesIO()
    Image.new("RGB", (8, 6), "red").save(output, format="PNG")
    upload_photo(app, "synthetic.png", output.getvalue())
    media_permission(app).check().run()
    app.checkbox(key="face_sdk_metrics_opt_in").uncheck().run()
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert next(item for item in app.tabs[1].file_uploader if item.label == "Short video (optional)").disabled
    assert app.session_state["personal_photo"].data
    assert "analysis" not in app.session_state


def test_revoking_google_metrics_opt_in_stops_camera_and_hides_summaries(app):
    class Camera:
        running = True
        stopping = False

        def stop(self, reason="user_off"):
            self.stopping = True

        def preview(self):
            return None, None

    class Session:
        def snapshot(self):
            raise AssertionError("Do not wait on a stalled face model after revocation.")

    class Explainer:
        summary = "An obsolete local summary"

        def reset(self):
            self.summary = None

    enable_face_features(app)
    camera, explainer = Camera(), Explainer()
    app.session_state["laptop_camera"] = camera
    app.session_state["live_session"] = Session()
    app.session_state["live_explainer"] = explainer
    app.checkbox(key="face_sdk_metrics_opt_in").uncheck().run()
    assert not app.exception
    assert camera.stopping
    assert explainer.summary is None
    assert button(app, "Start camera").disabled
    assert not app.tabs[0].metric
    assert "An obsolete local summary" not in messages(app.markdown)
    assert "stopping" in messages(app.info).lower()
    assert len(app.tabs[0].info) == 1


def test_initial_view_does_not_infer_without_analyze(app):
    assert app.title[0].value == "StressLens"
    assert app.tabs[1].radio[0].value == "My inputs"
    assert len(app.tabs) == 5
    assert app.tabs[0].label == "Live camera"
    assert len(app.tabs[2].expander) == 7
    assert not app.session_state["laptop_camera"].running
    assert "analysis" not in app.session_state
    assert not app.tabs[1].metric
    assert not app.get("imgs")


def test_live_camera_start_stop_updates_controls_without_real_hardware(app):
    enable_face_features(app)
    class Camera:
        running = False

        def start(self, index=0, *, segment_config=None):
            self.running = True

        def clear_report(self):
            pass

        def stop(self, reason="user_off"):
            self.running = False

        def preview(self):
            return None, None

    app.session_state["laptop_camera"] = Camera()
    button(app, "Start camera").click().run()
    assert not app.exception
    assert button(app, "Start camera").disabled
    assert not button(app, "Stop camera").disabled
    assert app.selectbox[0].disabled
    button(app, "Stop camera").click().run()
    assert not app.exception
    assert not button(app, "Start camera").disabled
    assert button(app, "Stop camera").disabled
    assert not app.selectbox[0].disabled


def test_live_research_cards_render_current_observations_and_sources(app):
    enable_face_features(app)
    next(item for item in app.tabs[0].checkbox if item.label == "Summarize significant changes with the local language model").uncheck().run()
    class Session:
        def snapshot(self):
            return {"status": "ok", "groups": {"Eye narrowing": 0.6},
                    "baseline": {"Eye narrowing": 0.2}, "changes": {"Eye narrowing": 0.4},
                    "history": [], "measurement_fps": 8, "latency_ms": 12, "frame_age_seconds": 0.1}
    app.session_state["live_session"] = Session()
    app.session_state["laptop_camera"] = SimpleNamespace(
        running=True, stopping=False, release_confirmed=False, preview=lambda: (None, None),
    )
    app.run()
    assert not app.exception
    text = messages(app.tabs[0].markdown)
    assert "Eye narrowing coefficient increased" in text
    assert "0.60 now versus 0.20" in text
    assert "Research connection:" in text
    assert "https://pmc.ncbi.nlm.nih.gov/articles/PMC10422124/" in text
    assert "Bright light or screen glare" in messages(app.tabs[0].caption)


def test_empty_own_inputs_requires_input(app):
    own_inputs(app)
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert "Add text, a photo/video, or your own rating first." in messages(app.warning)
    assert "analysis" not in app.session_state
    assert not app.tabs[1].metric


def test_uploaded_face_without_permission_is_blocked(app):
    enable_face_features(app)
    own_inputs(app)
    upload_photo(app, "sample_face.jpg", (ROOT / "assets" / "sample_face.jpg").read_bytes(), "image/jpeg")
    app.text_area[0].set_value(ENGLISH_TEXT)
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert "Please confirm permission" in messages(app.error)
    assert "analysis" not in app.session_state
    assert not app.tabs[1].metric


def test_text_only_runs_real_local_model_and_clear_removes_result(app):
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value
    own_inputs(app)
    app.text_area[0].set_value(ENGLISH_TEXT)
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    analysis = app.session_state["analysis"]
    assert analysis["example"] is False
    assert analysis["face"] is None
    assert analysis["self_report"] is None
    text_result = analysis["text"]
    assert text_result["status"] == "ok", text_result
    assert 0 <= text_result["stress_probability"] <= 1
    assert text_result["label"] in {"stress", "not_stress"}
    assert text_result["top_terms"]
    metrics = metric_values(app)
    assert metrics["Stress-language model score"] == f"{text_result['stress_probability']:.2f}"
    assert metrics["Face frames measured"] == "Not provided"
    assert metrics["Self-reported stress"] == "Not provided"
    assert "No photo or video was supplied." in messages(app.info)
    assert len(app.download_button) == 1
    button(app, "Clear analysis").click().run()
    assert not app.exception
    assert "analysis" not in app.session_state
    assert not app.tabs[1].metric
    assert not app.download_button


def test_zero_rating_is_preserved_as_an_intentional_value(app):
    own_inputs(app)
    app.checkbox(key="include_My inputs").check()
    app.slider[0].set_value(0)
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    analysis = app.session_state["analysis"]
    assert analysis["self_report"] == 0
    assert analysis["text"] is None
    assert analysis["face"] is None
    assert metric_values(app)["Self-reported stress"] == "0 / 10"
    assert "Your self-reported stress is 0/10" in analysis["summary"]


def test_short_text_abstains_in_ui(app):
    own_inputs(app)
    app.text_area[0].set_value("I feel stressed")
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert app.session_state["analysis"]["text"]["status"] == "insufficient"
    assert metric_values(app)["Stress-language model"] == "No estimate"
    assert "eight English words" in messages(app.warning)


def test_invalid_image_with_permission_shows_warning_without_crash(app):
    enable_face_features(app)
    own_inputs(app)
    upload_photo(app, "broken.png", b"not an image")
    media_permission(app).check()
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert "personal_photo" not in app.session_state
    assert "analysis" not in app.session_state
    assert app.error and app.warning


def test_research_search_no_match_then_restore_library(app):
    app.tabs[2].text_input[0].set_value("intergalactic zucchini hovercraft").run()
    assert not app.exception
    assert not app.tabs[2].expander
    assert "No matching note." in messages(app.info)
    app.tabs[2].text_input[0].set_value("").run()
    assert not app.exception
    assert len(app.tabs[2].expander) == 7


@pytest.mark.parametrize("metadata", [
    None,
    [],
    {"evaluation": None},
    {"evaluation": []},
    {"evaluation": {}},
    {"evaluation": {"accuracy": 0.8, "macro_f1": 0.7}},
    {"evaluation": {"accuracy": True, "macro_f1": 0.7, "test_rows": 10}},
    {"evaluation": {"accuracy": float("nan"), "macro_f1": 0.7, "test_rows": 10}},
    {"evaluation": {"accuracy": 1.2, "macro_f1": 0.7, "test_rows": 10}},
    {"evaluation": {"accuracy": 10 ** 400, "macro_f1": 0.7, "test_rows": 10}},
    {"evaluation": {"accuracy": 0.8, "macro_f1": -0.1, "test_rows": 10}},
    {"evaluation": {"accuracy": 0.8, "macro_f1": 0.7, "test_rows": 0}},
    {"evaluation": {"accuracy": 0.8, "macro_f1": 0.7, "test_rows": True}},
])
def test_invalid_evaluation_metadata_keeps_app_usable_without_false_metrics(app, monkeypatch, metadata):
    original_read = Path.read_text
    metrics_path = ROOT / "models" / "text_model_metrics.json"

    def read_text(path, *args, **kwargs):
        if path == metrics_path:
            return json.dumps(metadata)
        return original_read(path, *args, **kwargs)

    # Replace only the file read; keep the real rendering and actual file intact.
    monkeypatch.setattr(Path, "read_text", read_text)
    app.run()
    assert not app.exception
    assert len(app.tabs) == 5
    assert "evaluation file" in messages(app.tabs[3].warning).lower()
    assert not app.tabs[3].metric


@pytest.mark.face_sdk
def test_explicit_test_fixture_runs_both_real_models_and_input_mode_clears_result(app):
    enable_face_features(app)
    upload_photo(app, "sample_face.jpg", (ROOT / "assets" / "sample_face.jpg").read_bytes(), "image/jpeg")
    app.text_area[0].set_value(ENGLISH_TEXT)
    app.checkbox(key="include_My inputs").check()
    app.slider[0].set_value(7)
    media_permission(app).check()
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    analysis = app.session_state["analysis"]
    assert analysis["example"] is False
    assert analysis["text"]["status"] == "ok", analysis["text"]
    assert analysis["face"]["status"] == "ok", analysis["face"]
    assert analysis["face"]["face_frames"] == 1
    assert analysis["face"]["frames_analyzed"] == 1
    assert analysis["face"]["features"]
    assert metric_values(app)["Face frames measured"] == "1 / 1"
    assert metric_values(app)["Self-reported stress"] == "7 / 10"
    assert "not your probability" in messages(app.caption).lower()
    app.radio(key="analysis_input_choice").set_value("Fictional text example").run()
    assert "analysis" not in app.session_state
    assert not app.tabs[1].metric
def test_work_session_is_camera_free_and_preserves_existing_point_report(app, monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from stresslens.session_report import Measurement, SelfReport, to_export
    from stresslens.wellbeing_ui import CompanionState
    def forbidden(*args, **kwargs):
        raise AssertionError("Work session must not start camera or face SDK")
    monkeypatch.setattr("stresslens.live.cv2.VideoCapture", forbidden)
    monkeypatch.setattr("stresslens.live._detector", forbidden)
    assert [tab.label for tab in app.tabs][-1] == "Work session"
    state = CompanionState(history_path=tmp_path / "private" / "history.json")
    app.session_state["wellbeing_state"] = state
    workspace = app.session_state["report_workspace"]
    stamp = datetime(2026, 10, 18, 8, tzinfo=UTC)
    workspace.add_measurements([Measurement("fictional-hr-72", stamp, "heart_rate", 72, "bpm",
                                            "Fictional device", "Fictional practice", stamp)])
    retained_reading = workspace.snapshot().measurements[0]
    point = SelfReport("fictional-existing", datetime(2026, 10, 18, 8, tzinfo=UTC), "answered", 2)
    workspace.add_self_report(point)
    retained_point = workspace.snapshot().self_reports[0]
    prior_id = workspace.snapshot().report_id
    app.run()
    button(app, "Start work").click().run()
    app.selectbox(key="wellbeing_stress_0").set_value("0 · None")
    app.selectbox(key="wellbeing_clarity_0").set_value("Mixed")
    button(app, "Save check-in").click().run()
    assert not app.exception
    snapshot = workspace.snapshot()
    assert snapshot.report_id == prior_id and len(snapshot.self_reports) == 2
    assert snapshot.self_reports[0] is retained_point and snapshot.self_reports[0] == point
    assert snapshot.self_reports[1].value == 0
    assert snapshot.measurements[0] is retained_reading and snapshot.measurements[0].value == 72
    exported = to_export(snapshot, include_measurements=True)
    assert exported["schema"] == "session-report/2" and exported["measurements"][0]["value"] == 72
    assert "measurements" not in to_export(snapshot) and "stress_estimate" not in exported
    assert not app.session_state["laptop_camera"].running and not app.checkbox(key="face_sdk_metrics_opt_in").value
    assert not app.checkbox(key="wellbeing_keep_history").value and not state.history_path.exists()
    button(app, "End work").click().run()
    assert len(workspace.snapshot().self_reports) == 2 and not app.exception
