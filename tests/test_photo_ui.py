"""Real photo panel; synthetic camera and pixels, no SDK consent or device."""
import io
from types import SimpleNamespace

import numpy as np
from PIL import Image
from streamlit.testing.v1 import AppTest


PAGE = '''
import streamlit as st
from stresslens.photo_ui import render_photo_panel
render_photo_panel(st.session_state.camera, consented=True, key="synthetic_photo")
'''


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_photo_is_only_captured_by_explicit_action_and_retained_after_camera_off():
    camera = SimpleNamespace(running=False, stopping=False,
                             capture_photo=lambda: np.full((6, 8, 3), (10, 20, 30), dtype=np.uint8))
    app = AppTest.from_string(PAGE)
    app.session_state["camera"] = camera
    app.run()
    assert not app.exception
    assert button(app, "Capture photo").disabled
    assert "personal_photo" not in app.session_state
    camera.running = True
    app.run()
    assert "personal_photo" not in app.session_state
    button(app, "Capture photo").click().run()
    assert not app.exception
    photo = app.session_state["personal_photo"]
    assert Image.open(io.BytesIO(photo.data)).getpixel((0, 0)) == (10, 20, 30)
    camera.running = False
    app.run()
    assert app.session_state["personal_photo"] is photo
    assert button(app, "Retake photo").disabled
    button(app, "Remove photo").click().run()
    app.run()
    assert "personal_photo" not in app.session_state


def test_invalid_upload_keeps_the_previous_photo_and_current_result():
    camera = SimpleNamespace(running=True, stopping=False,
                             capture_photo=lambda: np.zeros((6, 8, 3), dtype=np.uint8))
    app = AppTest.from_string(PAGE)
    app.session_state["camera"] = camera
    app.run()
    button(app, "Capture photo").click().run()
    photo = app.session_state["personal_photo"]
    app.session_state["analysis"] = {"fictional_marker": "retained"}
    app.file_uploader[0].set_value(("corrupt.png", b"broken", "image/png")).run()
    assert not app.exception
    assert app.session_state["personal_photo"] is photo
    assert app.session_state["analysis"]["fictional_marker"] == "retained"
    assert app.error


def test_rejected_retake_keeps_the_previous_photo_and_result():
    def unavailable():
        raise RuntimeError("No fresh camera frame is available.")

    camera = SimpleNamespace(running=True, stopping=False,
                             capture_photo=lambda: np.zeros((6, 8, 3), dtype=np.uint8))
    app = AppTest.from_string(PAGE)
    app.session_state["camera"] = camera
    app.run()
    button(app, "Capture photo").click().run()
    photo = app.session_state["personal_photo"]
    app.session_state["analysis"] = {"fictional_marker": "retained"}
    camera.capture_photo = unavailable
    button(app, "Retake photo").click().run()
    assert not app.exception and app.error
    assert app.session_state["personal_photo"] is photo
    assert app.session_state["analysis"]["fictional_marker"] == "retained"
