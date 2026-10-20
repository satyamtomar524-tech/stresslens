"""Camera-off app integration; photos/face results are explicitly synthetic."""
import io
import json
from pathlib import Path

import pytest
from PIL import Image
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]
TEXT = "Fictional example: several unfinished tasks are worrying me, and I need time to plan tomorrow."


def picture(color):
    output = io.BytesIO()
    Image.new("RGB", (12, 10), color).save(output, format="PNG")
    return output.getvalue()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def upload(app, color="red"):
    uploader = next(item for item in app.tabs[1].file_uploader if item.label.startswith("Upload "))
    uploader.set_value(("SYNTHETIC.png", picture(color), "image/png")).run()
    assert not app.exception
    return app.session_state["personal_photo"]


@pytest.fixture
def app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not app.exception
    app.radio(key="analysis_input_choice").set_value("My inputs").run()
    return app


def test_personal_photo_is_retained_but_not_exposed_in_fictional_views(app):
    photo = upload(app)
    before = app.session_state["report_workspace"].snapshot()
    app.radio(key="analysis_input_choice").set_value("Fictional text example").run()
    assert not app.exception
    assert not app.tabs[1].get("imgs")
    assert app.session_state["personal_photo"] is photo
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value
    button(app, "Analyze example").click().run()
    assert not app.exception
    assert app.session_state["analysis"]["face"] is None
    assert app.session_state["analysis"]["self_report"] is None
    assert app.session_state["analysis"]["photo"] is None
    button(app, "Explore a fictional week").click().run()
    assert not app.exception and not app.get("imgs")
    assert app.session_state["personal_photo"] is photo
    button(app, "Return to my session").click().run()
    app.radio(key="analysis_input_choice").set_value("My inputs").run()
    assert app.session_state["personal_photo"] is photo
    assert app.session_state["report_workspace"].snapshot() == before


def test_selected_photo_is_analyzed_and_replacement_removal_invalidate_exports(app, monkeypatch):
    import streamlit as st

    received, downloads = [], {}
    original_download = st.download_button

    def capture_download(label, data, *args, **kwargs):
        downloads[label] = data
        return original_download(label, data, *args, **kwargs)

    def synthetic_face(data):
        received.append(data)
        return {"status": "ok", "mode": "image", "face_frames": 1, "frames_analyzed": 1,
                "features": {"mouthSmileLeft": 0.2, "mouthSmileRight": 0.4},
                "annotated_image": picture("green"), "timeline": [], "warnings": []}

    monkeypatch.setattr(st, "download_button", capture_download)
    monkeypatch.setattr("stresslens.face.analyze_image", synthetic_face)
    photo = upload(app)
    app.checkbox(key="face_sdk_metrics_opt_in").check().run()
    next(item for item in app.tabs[1].checkbox if item.label.startswith("This is my")).check()
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert received == [photo.data]
    exported = json.loads(downloads["Download this result (JSON)"])
    assert exported["photo"]["source"] == "upload"
    assert "annotated_image" not in exported["face"]
    details = next(item for item in app.tabs[1].expander if item.label == "More details · this result")
    assert not details.proto.expanded and details.download_button
    upload(app, "blue")
    assert "analysis" not in app.session_state and not app.tabs[1].download_button
    next(item for item in app.tabs[1].button if item.label == "Remove photo").click().run()
    app.run()
    assert "personal_photo" not in app.session_state and "analysis" not in app.session_state


def test_photo_can_be_held_for_later_while_text_analysis_keeps_camera_off(app, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Text-only analysis must not invoke face processing")
    monkeypatch.setattr("stresslens.face.analyze_image", forbidden)
    photo = upload(app)
    app.text_area[0].set_value(TEXT)
    button(app, "Analyze my inputs").click().run()
    assert not app.exception
    assert app.session_state["analysis"]["text"]["status"] == "ok"
    assert app.session_state["analysis"]["face"] is None
    assert app.session_state["personal_photo"] is photo
    assert not app.checkbox(key="face_sdk_metrics_opt_in").value
    assert not app.session_state["laptop_camera"].running
    details = next(item for item in app.tabs[1].expander if item.label == "More details · this result")
    assert {item.label for item in details.metric} >= {"Stress-language model score", "Face frames measured"}
    assert any("Analysis time (UTC):" in item.value for item in details.caption)
    assert "uncalibrated" not in app.session_state["analysis"]["overview"]
    photo_help = next(item for item in app.tabs[1].expander if item.label == "Photo help")
    assert not photo_help.proto.expanded
    assert any("Selection time (UTC):" in item.value for item in photo_help.caption)


def test_report_and_work_tables_are_optional_without_losing_exports(app):
    work = app.tabs[4]
    work.selectbox[0].set_value("1 · Low")
    work.selectbox[1].set_value("Mixed")
    button(app, "Save check-in").click().run()
    assert not app.exception
    work_details = next(item for item in app.tabs[4].expander if item.label == "More details · check-in counts")
    assert not work_details.proto.expanded and len(work_details.dataframe) == 2
    report_details = next(item for item in app.tabs[0].expander if item.label == "More details · session report")
    assert not report_details.proto.expanded
    assert {item.label for item in report_details.download_button} == {"Download session JSON", "Download session TXT"}


def test_clear_analysis_and_report_do_not_remove_the_selected_photo(app):
    photo = upload(app)
    app.text_area[0].set_value(TEXT)
    button(app, "Analyze my inputs").click().run()
    button(app, "Clear analysis").click().run()
    assert not app.exception and app.session_state["personal_photo"] is photo
    app.tabs[4].selectbox[0].set_value("Skip")
    button(app, "Save check-in").click().run()
    button(app, "Clear report").click().run()
    assert not app.exception and app.session_state["personal_photo"] is photo
    assert not app.session_state["report_workspace"].snapshot().self_reports


def test_failed_photo_analysis_retains_selection_and_reports_unavailable(app, monkeypatch):
    monkeypatch.setattr("stresslens.face.analyze_image", lambda data: {
        "status": "error", "error": "Synthetic processor failure", "face_frames": 0, "frames_analyzed": 0,
    })
    photo = upload(app)
    app.checkbox(key="face_sdk_metrics_opt_in").check().run()
    next(item for item in app.tabs[1].checkbox if item.label.startswith("This is my")).check()
    button(app, "Analyze my inputs").click().run()
    assert not app.exception and app.session_state["personal_photo"] is photo
    result = app.session_state["analysis"]
    assert result["face"]["status"] == "error"
    assert "unavailable for this input" in result["overview"]
    assert result["photo"]["selected_at_utc"] == photo.selected_at.isoformat()
