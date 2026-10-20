import io
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest
from PIL import Image

from stresslens.face import analyze_image, analyze_video, serializable_result

ROOT = Path(__file__).resolve().parents[1]


def image_bytes(image):
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.face_sdk
def test_real_face_model_returns_measurements_not_stress():
    result = analyze_image((ROOT / "assets/sample_face.jpg").read_bytes())
    assert result["status"] == "ok"
    assert result["face_frames"] == 1
    assert len(result["features"]) == 52
    assert all(0 <= value <= 1 for value in result["features"].values())
    assert "stress_score" not in result
    assert "annotated_image" not in serializable_result(result)
    Image.open(io.BytesIO(result["annotated_image"])).verify()


@pytest.mark.face_sdk
def test_no_face_is_not_fabricated_measurement():
    result = analyze_image(image_bytes(Image.new("RGB", (300, 300), "white")))
    assert result["status"] == "no_face"
    assert not result["features"]


def test_corrupt_and_oversize_input():
    assert analyze_image(b"broken image")["status"] == "invalid"
    assert analyze_image(b"")["status"] == "invalid"
    assert analyze_video(b"", ".mp4")["status"] == "invalid"
    assert analyze_video(b"invalid", ".exe")["status"] == "invalid"
    assert analyze_video(b"invalid", ".mp4")["status"] == "invalid"


@pytest.mark.face_sdk
def test_extremely_narrow_image_does_not_crash():
    result = analyze_image(image_bytes(Image.new("RGB", (4096, 1), "white")))
    assert result["status"] in {"no_face", "invalid", "error"}


@pytest.mark.face_sdk
def test_multiple_faces_rejected():
    source = Image.open(ROOT / "assets/sample_face.jpg").convert("RGB")
    source.thumbnail((400, 500))
    pair = Image.new("RGB", (source.width * 2, source.height))
    pair.paste(source, (0, 0))
    pair.paste(source, (source.width, 0))
    assert analyze_image(image_bytes(pair))["status"] == "multiple_faces"


@pytest.mark.face_sdk
def test_missing_face_model_reported(tmp_path):
    result = analyze_image((ROOT / "assets/sample_face.jpg").read_bytes(), tmp_path / "absent.task")
    assert result["status"] == "error"
    assert "missing" in result["message"]


@pytest.mark.face_sdk
def test_real_video_path_and_timing(tmp_path):
    source = cv2.imread(str(ROOT / "assets/sample_face.jpg"))
    source = cv2.resize(source, (410, 512))
    file = tmp_path / "repeated_test_portrait.avi"
    writer = cv2.VideoWriter(str(file), cv2.VideoWriter_fourcc(*"MJPG"), 10, (410, 512))
    assert writer.isOpened()
    for _ in range(20):
        writer.write(source)
    writer.release()
    result = analyze_video(file.read_bytes(), ".avi")
    assert result["status"] == "ok"
    assert 1 < result["face_frames"] <= result["frames_analyzed"] <= 120
    times = [row["seconds"] for row in result["timeline"]]
    assert times == sorted(set(times))
    assert result["duration_seconds"] == 2
    assert not any("stress" in feature for feature in result["features"])


def test_long_video_rejected_before_model(tmp_path):
    file = tmp_path / "long.avi"
    writer = cv2.VideoWriter(str(file), cv2.VideoWriter_fourcc(*"MJPG"), 1, (32, 32))
    assert writer.isOpened()
    for _ in range(31):
        writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
    writer.release()
    result = analyze_video(file.read_bytes(), ".avi", tmp_path / "absent.task")
    assert result["status"] == "invalid"
    assert "longer than 30" in result["message"]


def analyze_sampled_video(monkeypatch, samples):
    """Exercise the real analyzer with deterministic decoder and face-model boundaries."""
    class Capture:
        index = 0

        def isOpened(self):
            return True

        def get(self, prop):
            return {cv2.CAP_PROP_FPS: 4, cv2.CAP_PROP_FRAME_COUNT: len(samples),
                    cv2.CAP_PROP_FRAME_WIDTH: 40, cv2.CAP_PROP_FRAME_HEIGHT: 40}[prop]

        def set(self, prop, value):
            assert prop == cv2.CAP_PROP_POS_FRAMES
            self.index = value
            return True

        def read(self):
            value = samples[self.index]
            return (False, None) if value is None else (True, np.full((40, 40, 3), value, dtype=np.uint8))

        def release(self):
            pass

    class Detector:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def detect_for_video(self, image, timestamp):
            has_face = bool(image.numpy_view().any())
            return SimpleNamespace(
                face_landmarks=[[SimpleNamespace(x=0.5, y=0.5, z=0.0)]] if has_face else [],
                face_blendshapes=[[SimpleNamespace(category_name="jawOpen", score=0.2)]] if has_face else [],
                facial_transformation_matrixes=[],
            )

    monkeypatch.setattr("stresslens.face.cv2.VideoCapture", lambda path: Capture())
    monkeypatch.setattr("stresslens.face._detector", lambda *args, **kwargs: Detector())
    return analyze_video(b"synthetic test data")


def test_mostly_undecodable_video_is_insufficient(monkeypatch, mock_face_sdk):
    result = analyze_sampled_video(monkeypatch, [255, None, None, None])
    assert result["status"] == "insufficient"
    assert result["frames_requested"] == 4
    assert result["frames_analyzed"] == 1
    assert result["decode_failures"] == 3
    assert result["face_frames"] == 1
    assert not result["features"]


def test_video_timeline_preserves_decode_and_no_face_gaps(monkeypatch, mock_face_sdk):
    result = analyze_sampled_video(monkeypatch, [255, None, 0, 255])
    assert result["status"] == "ok"
    assert [row["seconds"] for row in result["timeline"]] == [0.0, 0.25, 0.5, 0.75]
    assert result["frames_requested"] == 4
    assert result["frames_analyzed"] == 3
    assert result["decode_failures"] == 1
    assert result["face_frames"] == 2
    for row in result["timeline"][1:3]:
        assert row == {"seconds": row["seconds"], "Brow lowering": None, "Eye narrowing": None,
                       "Lip pressing": None, "Smile shape": None, "Eye closure": None, "Jaw opening": None}
    assert result["timeline"][0]["Jaw opening"] == 0.2
    assert result["timeline"][3]["Jaw opening"] == 0.2
    assert any("decode" in warning.lower() for warning in result["warnings"])


def test_face_coverage_uses_all_requested_samples(monkeypatch, mock_face_sdk):
    result = analyze_sampled_video(monkeypatch, [255, None, 0, None])
    assert result["status"] == "insufficient"
    assert result["face_frames"] == 1
    assert result["frames_analyzed"] == 2
    assert result["frames_requested"] == 4
