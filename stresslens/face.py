"""Measure facial blendshapes locally; never translate them into stress severity."""
from __future__ import annotations

import io
import math
import tempfile
import warnings
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

MODEL_PATH = Path(__file__).resolve().parents[1] / "models" / "face_landmarker.task"
MAX_BYTES = 40 * 1024 * 1024
MAX_PIXELS = 20_000_000
MAX_SECONDS = 30
FEATURE_LABELS = {
    "Brow lowering": ("browDownLeft", "browDownRight"),
    "Eye narrowing": ("eyeSquintLeft", "eyeSquintRight"),
    "Lip pressing": ("mouthPressLeft", "mouthPressRight"),
    "Smile shape": ("mouthSmileLeft", "mouthSmileRight"),
    "Eye closure": ("eyeBlinkLeft", "eyeBlinkRight"),
    "Jaw opening": ("jawOpen",),
}


def _empty(message: str, mode="image", status="invalid") -> dict:
    return dict(status=status, mode=mode, message=message, features={},
                frames_analyzed=0, face_frames=0, timeline=[], warnings=[])


def feature_groups(features: dict) -> dict:
    return {name: float(np.mean([features.get(k, 0.0) for k in keys]))
            for name, keys in FEATURE_LABELS.items()}


def _detector(model_path: Path, video=False):
    if not model_path.is_file():
        raise FileNotFoundError("Face model missing. Run scripts/setup_models.py.")
    import mediapipe as mp
    options = mp.tasks.vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_buffer=model_path.read_bytes()),
        running_mode=(mp.tasks.vision.RunningMode.VIDEO if video
                      else mp.tasks.vision.RunningMode.IMAGE),
        num_faces=2, output_face_blendshapes=True,
        min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
    )
    return mp.tasks.vision.FaceLandmarker.create_from_options(options)


def _extract(result) -> dict:
    return {item.category_name: float(item.score) for item in result.face_blendshapes[0]}


def _preview(rgb: np.ndarray, landmarks) -> bytes:
    picture = Image.fromarray(rgb)
    draw = ImageDraw.Draw(picture)
    w, h = picture.size
    for point in landmarks[::3]:
        x, y = point.x * w, point.y * h
        draw.ellipse((x-1.4, y-1.4, x+1.4, y+1.4), fill="#30E1C2")
    output = io.BytesIO()
    picture.save(output, format="PNG")
    return output.getvalue()


def _resize(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[:2]
    if max(h, w) > 1280:
        rgb = cv2.resize(rgb, (max(1, round(w * 1280 / max(h, w))), max(1, round(h * 1280 / max(h, w)))))
    return np.ascontiguousarray(rgb)


def analyze_image(data: bytes, model_path: Path | None = None) -> dict:
    if not data or len(data) > MAX_BYTES:
        return _empty("Choose an image smaller than 40 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.width * source.height > MAX_PIXELS:
                    return _empty("Image is too large. Use an image below 20 megapixels.")
                rgb = _resize(np.asarray(ImageOps.exif_transpose(source).convert("RGB")))
    except (UnidentifiedImageError, OSError, ValueError, cv2.error, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        return _empty("This file could not be decoded as a supported image.")
    try:
        import mediapipe as mp
        with _detector(model_path or MODEL_PATH) as detector:
            result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    except (FileNotFoundError, RuntimeError, ValueError, OSError) as exc:
        return _empty(f"Face model unavailable: {exc}", status="error")
    count = len(result.face_landmarks)
    if count == 0:
        return {**_empty("No face was detected. Try a clear, front-facing image.", status="no_face"),
                "frames_analyzed": 1}
    if count != 1:
        return _empty("More than one face was detected. Please use a single-person image.", status="multiple_faces")
    return dict(status="ok", mode="image", message="One face measured.",
                features=_extract(result), frames_analyzed=1, face_frames=1,
                annotated_image=_preview(rgb, result.face_landmarks[0]), timeline=[],
                warnings=["A still image cannot measure changes over time or establish stress.",
                          "Blendshapes are model coefficients, not FACS-certified action units or stress probabilities."])


def analyze_video(data: bytes, suffix=".mp4", model_path: Path | None = None) -> dict:
    if not data or len(data) > MAX_BYTES:
        return _empty("Choose a video smaller than 40 MB.", "video")
    if suffix.lower() not in {".mp4", ".mov", ".avi", ".webm"}:
        return _empty("Use MP4, MOV, AVI, or WebM.", "video")
    rows, timeline, preview = [], [], None
    sampled = requested = decode_failures = 0
    try:
        with tempfile.TemporaryDirectory(prefix="stresslens-") as folder:
            path = Path(folder) / ("clip" + suffix.lower())
            path.write_bytes(data)
            capture = cv2.VideoCapture(str(path))
            try:
                if not capture.isOpened():
                    return _empty("The video could not be decoded. Try an H.264 MP4.", "video")
                fps = capture.get(cv2.CAP_PROP_FPS)
                frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
                if not math.isfinite(fps) or fps <= 0 or not math.isfinite(frame_count) or frame_count <= 0:
                    return _empty("Video timing is unavailable. Re-export as MP4.", "video")
                duration = frame_count / fps
                if duration > MAX_SECONDS + 0.05:
                    return _empty("Video is longer than 30 seconds. Trim it before uploading.", "video")
                if capture.get(cv2.CAP_PROP_FRAME_WIDTH) * capture.get(cv2.CAP_PROP_FRAME_HEIGHT) > MAX_PIXELS:
                    return _empty("Video resolution is too large. Use 1080p or lower.", "video")
                import mediapipe as mp
                with _detector(model_path or MODEL_PATH, video=True) as detector:
                    indices = np.unique(np.linspace(0, frame_count - 1, min(120, max(1, math.ceil(duration * 4)))).astype(int))
                    requested = len(indices)
                    previous_timestamp = -1
                    for index in indices:
                        timestamp = max(previous_timestamp + 1, round(index * 1000 / fps))
                        previous_timestamp = timestamp
                        sample = {"seconds": timestamp / 1000, **dict.fromkeys(FEATURE_LABELS)}
                        timeline.append(sample)
                        capture.set(cv2.CAP_PROP_POS_FRAMES, int(index))
                        ok, frame = capture.read()
                        if not ok:
                            decode_failures += 1
                            continue
                        sampled += 1
                        rgb = _resize(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                        result = detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                        if len(result.face_landmarks) > 1:
                            return _empty("Multiple faces appeared in the clip. Use a single-person video.", "video", "multiple_faces")
                        if not result.face_landmarks:
                            continue
                        features = _extract(result)
                        rows.append(features)
                        sample.update(feature_groups(features))
                        if preview is None:
                            preview = _preview(rgb, result.face_landmarks[0])
            finally:
                capture.release()
    except (FileNotFoundError, RuntimeError, ValueError, OSError, cv2.error) as exc:
        return _empty(f"Video analysis could not finish: {exc}", "video", "error")
    coverage = dict(frames_requested=requested, frames_analyzed=sampled, decode_failures=decode_failures,
                    face_frames=len(rows), timeline=timeline, duration_seconds=round(duration, 2))
    gap_warnings = []
    if decode_failures:
        gap_warnings.append(f"{decode_failures} of {requested} scheduled samples could not be decoded; these appear as gaps.")
    if sampled > len(rows):
        gap_warnings.append(f"No face was detected in {sampled - len(rows)} decoded samples; these appear as gaps.")
    if sampled / max(1, requested) < 0.5:
        return {**_empty("Fewer than half the scheduled video samples could be decoded. Re-export the clip and try again.", "video", "insufficient"),
                **coverage, "warnings": gap_warnings}
    if not rows:
        return {**_empty("No face was detected in the sampled video frames.", "video", "no_face"),
                **coverage, "warnings": gap_warnings}
    if len(rows) / max(1, requested) < 0.5:
        return {**_empty("A face was visible in fewer than half the scheduled video samples. Try a clearer clip.", "video", "insufficient"),
                **coverage, "warnings": gap_warnings}
    means = {key: float(np.mean([row[key] for row in rows])) for key in rows[0]}
    return dict(status="ok", mode="video", message="Facial movement coefficients measured in sampled video frames.",
                features=means, **coverage, annotated_image=preview,
                warnings=gap_warnings + ["Charts show sampled model coefficients over time; they do not measure stress severity.",
                          "Sampling at about 4 frames/second is not suitable for blink-rate or microexpression measurement.",
                          "Speaking, lighting, pose and movement can change these measurements."])


def serializable_result(result: dict | None) -> dict | None:
    return {k: v for k, v in result.items() if k != "annotated_image"} if result else None
