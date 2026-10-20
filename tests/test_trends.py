"""Regression checks for honest live chart gaps and pending camera shutdown."""
import json
from pathlib import Path
from types import SimpleNamespace

from streamlit.dataframe_util import convert_arrow_bytes_to_pandas_df
from streamlit.testing.v1 import AppTest

from stresslens.face import FEATURE_LABELS


ROOT = Path(__file__).resolve().parents[1]


class SyntheticSession:
    def snapshot(self):
        groups = {name: 0.2 for name in FEATURE_LABELS}
        return {
            "status": "ok", "groups": groups, "baseline": None, "changes": {},
            "measurement_fps": 10, "latency_ms": 12, "frame_age_seconds": 0.0,
            "history": [
                {"seconds": seconds, **{name: value for name in FEATURE_LABELS}}
                for seconds, value in [(0.0, 0.2), (0.1, None), (0.2, None),
                                       (0.3, 0.8), (0.4, 0.9)]
            ],
        }


def prepared_app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    app.checkbox(key="face_sdk_metrics_opt_in").check().run()
    next(
        item for item in app.tabs[0].checkbox
        if item.label == "Summarize significant changes with the local language model"
    ).uncheck().run()
    assert app.checkbox(key="face_sdk_metrics_opt_in").value
    app.session_state["live_session"] = SyntheticSession()
    # A synthetic current reading requires an active, fresh synthetic camera.
    # No device is started: the adapter only supplies presentation state.
    app.session_state["laptop_camera"] = SimpleNamespace(
        running=True, stopping=False, release_confirmed=False, preview=lambda: (None, None),
    )
    return app


def test_live_chart_preserves_missing_samples_and_latest_measurement():
    app = prepared_app().run()
    assert not app.exception
    chart = app.get("vega_lite_chart")[0].proto
    payload = chart.datasets[0].data.data if chart.datasets else chart.data.data
    data = convert_arrow_bytes_to_pandas_df(payload)
    # Accept wide or long chart data, while checking the actual emitted samples.
    if "Brow lowering" in data:
        brow = data.rename(columns={"Brow lowering": "coefficient"})
    else:
        brow = data[data["color -- streamlit-generated"] == "Brow lowering"].rename(
            columns={"value -- streamlit-generated": "coefficient"})
    assert brow["seconds"].tolist() == [0.0, 0.1, 0.2, 0.3, 0.4]
    assert brow["coefficient"].isna().tolist() == [False, True, True, False, False]
    assert brow["coefficient"].iloc[-1] == 0.9
    spec = json.loads(chart.spec)
    assert spec["mark"]["invalid"] == "break-paths-show-domains"


def test_stopping_camera_does_not_show_old_readings_or_enable_restart():
    class StoppingCamera:
        running = True
        stopping = True

        def preview(self):
            return None, None

    app = prepared_app()
    app.session_state["laptop_camera"] = StoppingCamera()
    app.run()
    assert not app.exception
    buttons = {item.label: item for item in app.button}
    assert buttons["Start camera"].disabled
    assert buttons["Stop camera"].disabled
    assert buttons["Capture reference · 8s"].disabled
    assert buttons["Clear reference"].disabled
    assert not app.tabs[0].metric
    assert not app.get("vega_lite_chart")
    assert "stopping" in " ".join(item.value for item in app.info).lower()


def test_video_coverage_metric_counts_all_scheduled_samples():
    app = prepared_app()
    app.session_state["analysis"] = {
        "example": False, "text": None, "self_report": None, "summary": "Insufficient video.",
        "photo_revision": 0, "photo": None, "media_source": "video",
        "created_utc": "2026-10-19T12:00:00+00:00",
        "face": {"mode": "video", "status": "insufficient", "face_frames": 1,
                 "frames_analyzed": 1, "frames_requested": 40, "decode_failures": 39,
                 "message": "Fewer than half the scheduled samples could be decoded."},
    }
    app.run()
    assert not app.exception
    metrics = {item.label: item.value for item in app.tabs[1].metric}
    assert metrics["Face frames measured"] == "1 / 40"
