"""Continuous local camera processing with bounded, thread-safe measurement state."""
from __future__ import annotations

import copy
import platform
import threading
import time
from collections import deque
from datetime import UTC, datetime

import cv2
import numpy as np

from stresslens.face import MODEL_PATH, FEATURE_LABELS, _detector, _extract, _resize, feature_groups
from stresslens.session_report import SegmentConfig


class LiveFaceSession:
    """One model per camera session. Stores numeric history, never recordings."""

    def __init__(self, detector_factory=None, clock=time.monotonic, report_workspace=None):
        self._factory = detector_factory or (lambda: _detector(MODEL_PATH, video=True))
        self._clock = clock
        self._lock = threading.RLock()
        self._detector = None
        self._started = None
        self._last_sample = -float("inf")
        self._last_timestamp = -1
        self._last_frame = None
        self._history = deque(maxlen=600)
        self._groups = {}
        self._baseline = None
        self._calibration = None
        self._frames = 0
        self._snapshot = {"status": "waiting", "message": "Start the camera to begin.", "groups": {}}
        # Lock order: live state -> report attachment -> workspace -> accumulator.
        # Deadline finalization takes only the report lock, never inference's lock.
        self.report_workspace = report_workspace
        self._report_lock = threading.RLock()
        self._report_segment = None
        self._report_accepting = False
        self._last_report = None
        self._report_error = None

    @property
    def clock(self):
        return self._clock

    @property
    def report_error(self):
        with self._report_lock:
            return self._report_error

    def begin_segment(self, config, start_utc, start_monotonic):
        """Attach at explicit Start, before opening capture or seeing a frame."""
        if self.report_workspace is None:
            return None
        with self._lock, self._report_lock:
            if self._report_segment is not None:
                if self._report_error:
                    raise RuntimeError("Previous report finalization failed; resolve it before restart")
                return self._report_segment
            if self._detector is not None:
                raise RuntimeError("Stop previous live processing before a new segment")
            segment = self.report_workspace.start_segment(config, start_utc, start_monotonic)
            self._report_segment = segment
            self._report_accepting = True
            self._report_error = None
            self._started = start_monotonic
            self._last_frame = None
            self._last_timestamp = -1
            self._last_sample = -float("inf")
            self._history.clear()
            self._groups = {}
            self._baseline = self._calibration = None
            self._frames = 0
            self._snapshot = {"status": "waiting", "message": "Starting observation segment.", "groups": {}}
            return segment

    def segment_deadline(self):
        with self._report_lock:
            if self._report_segment is None or not self._report_accepting:
                return None
            segment = self._report_segment
            reason = "timer_end" if segment.config.timer_seconds is not None else "resource_limit"
            return segment.start_monotonic + segment.config.deadline, reason

    def _observe_report(self, now, groups, status):
        with self._report_lock:
            if self._report_segment is not None and self._report_accepting:
                self._report_segment.observe(now - self._report_segment.start_monotonic,
                                             groups, None if groups else status)

    def _copy_report_reference(self):
        with self._report_lock:
            if self._report_segment is not None and self._report_accepting:
                self._report_segment.set_reference(self._baseline)

    def finish_segment(self, reason="user_off", now=None):
        """Freeze numeric data independently of capture/inference release."""
        with self._report_lock:
            if self._report_segment is None:
                return self._last_report
            self._report_accepting = False
            elapsed = (self._clock() if now is None else now) - self._report_segment.start_monotonic
            try:
                report = self.report_workspace.finish_segment(max(0, elapsed), reason)
            except Exception as exc:
                self._report_error = str(exc)
                raise
            self._last_report = report
            self._report_segment = None
            self._report_error = None
            return report

    def clear_report(self):
        with self._lock, self._report_lock:
            if self._report_segment is not None or self._detector is not None:
                raise RuntimeError("Finish live processing before clearing report data")
            if self.report_workspace is not None:
                self.report_workspace.clear()
            self._last_report = self._report_error = None
            self._baseline = self._calibration = None

    def capture_reference(self, seconds=8):
        with self._lock:
            self._baseline = None
            self._snapshot.pop("reference_message", None)
            self._calibration = {"start": self._clock(), "seconds": float(seconds), "seen": 0, "rows": []}

    def clear_reference(self):
        with self._lock:
            self._baseline = self._calibration = None
            self._snapshot.pop("reference_message", None)

    def _update_reference(self, now, groups):
        if not self._calibration:
            return
        task = self._calibration
        task["seen"] += 1
        if groups:
            task["rows"].append(groups)
        if now - task["start"] >= task["seconds"]:
            rows = task["rows"]
            if len(rows) >= max(5, int(task["seconds"] * 3)) and len(rows) / task["seen"] >= 0.8:
                self._baseline = {k: float(np.mean([r[k] for r in rows])) for k in FEATURE_LABELS}
                self._copy_report_reference()
                self._snapshot["reference_message"] = "Reference captured. Changes are measured relative to this face position/expression."
            else:
                self._snapshot["reference_message"] = "Reference failed: keep one clear face in view and try again."
            self._calibration = None

    def process(self, rgb: np.ndarray, *, stop_requested=None) -> np.ndarray:
        """Process at up to 10 Hz; return an annotated moving video frame."""
        with self._lock:
            if stop_requested is not None and stop_requested():
                return rgb.copy()
            now = self._clock()
            self._last_frame = now
            rgb = _resize(rgb)
            if self._started is None:
                self._started = now
            if now - self._last_sample >= 0.09:
                self._last_sample = now
                began = time.perf_counter()
                groups = {}
                try:
                    import mediapipe as mp
                    if self._detector is None:
                        self._detector = self._factory()
                    timestamp = max(self._last_timestamp + 1, round((now - self._started) * 1000))
                    self._last_timestamp = timestamp
                    result = self._detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), timestamp)
                    if stop_requested is not None and stop_requested():
                        return rgb.copy()  # Inference crossed a terminal boundary.
                    self._frames += 1
                    count = len(result.face_landmarks)
                    if count == 1:
                        points = result.face_landmarks[0]
                        width = max(p.x for p in points) - min(p.x for p in points)
                        if width < 0.14:
                            self._set_unavailable("too_far", "Move closer to the camera.")
                            groups = {}
                        else:
                            raw = feature_groups(_extract(result))
                            self._groups = {k: 0.35 * v + 0.65 * self._groups.get(k, v) for k, v in raw.items()}
                            groups = self._groups.copy()
                            self._snapshot.update(status="ok", message="One face tracked live.", groups=groups,
                                                  landmarks=[(p.x, p.y) for p in points[::4]])
                    elif count > 1:
                        self._set_unavailable("multiple_faces", "Use one person at a time; measurements paused.")
                        groups = {}
                    else:
                        self._set_unavailable("no_face", "No face detected. Look toward the camera.")
                        groups = {}
                    self._snapshot["latency_ms"] = round((time.perf_counter() - began) * 1000, 1)
                    self._update_reference(now, groups)
                    self._history.append({"seconds": round(now - self._started, 2),
                                          **{k: groups.get(k) for k in FEATURE_LABELS}})
                except (RuntimeError, OSError, ValueError, cv2.error) as exc:
                    if stop_requested is not None and stop_requested():
                        return rgb.copy()
                    self._set_unavailable("error", f"Face processing failed: {exc}")
                    groups = {}
                    self._update_reference(now, {})
                    self._history.append({"seconds": round(now - self._started, 2),
                                          **dict.fromkeys(FEATURE_LABELS)})
                self._observe_report(now, groups, self._snapshot.get("status", "unavailable"))
            canvas = rgb.copy()
            if self._snapshot.get("status") == "ok":
                h, w = canvas.shape[:2]
                for x, y in self._snapshot.get("landmarks", []):
                    cv2.circle(canvas, (round(x * w), round(y * h)), 1, (48, 225, 194), -1)
            cv2.rectangle(canvas, (0, 0), (canvas.shape[1], 38), (16, 35, 52), -1)
            cv2.putText(canvas, "LIVE | " + self._snapshot.get("message", "Waiting"), (12, 25),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 255, 250), 1, cv2.LINE_AA)
            return canvas

    def _set_unavailable(self, status, message):
        self._groups = {}
        self._snapshot.update(status=status, message=message, groups={}, landmarks=[])

    def snapshot(self):
        with self._lock:
            result = copy.deepcopy({k: v for k, v in self._snapshot.items() if k != "landmarks"})
            result.update(frames=self._frames, history=list(self._history), baseline=copy.deepcopy(self._baseline))
            now = self._clock()
            result["frame_age_seconds"] = None if self._last_frame is None else round(now - self._last_frame, 2)
            if self._last_frame is not None and now - self._last_frame > 2:
                result.update(status="stale", message="Camera frames stopped arriving. No current reading.", groups={})
            if self._calibration:
                result["reference_progress"] = min(1.0, (now - self._calibration["start"]) / self._calibration["seconds"])
            if result.get("status") == "ok" and self._baseline:
                result["changes"] = {k: round(result["groups"][k] - self._baseline[k], 3) for k in FEATURE_LABELS}
            else:
                result["changes"] = {}
            recent = [r for r in self._history if self._started is not None and r["seconds"] >= now - self._started - 5]
            result["measurement_fps"] = round((len(recent) - 1) / max(0.1, recent[-1]["seconds"] - recent[0]["seconds"]), 1) if len(recent) > 1 else 0.0
            return result

    def stop(self, reason="user_off", now=None):
        errors = []
        try:
            self.finish_segment(reason, now)
        except Exception as exc:
            errors.append(str(exc))
        with self._lock:
            try:
                if self._detector is not None:
                    self._detector.close()
            except Exception as exc:
                errors.append(str(exc))
            finally:
                self._detector = None
                self._started = self._last_frame = None
                self._last_timestamp = -1
                self._last_sample = -float("inf")
                self._history.clear()
                self._groups = {}
                self._baseline = self._calibration = None
                self._frames = 0
                self._snapshot = {"status": "stopped", "message": "Camera stopped.", "groups": {}}
        if errors:
            raise RuntimeError("Live cleanup failed: " + "; ".join(errors))


class LaptopCamera:
    """Direct webcam adapter for this local laptop, with explicit Start/Stop."""

    def __init__(self, session: LiveFaceSession, capture_factory=None, utc_clock=None):
        self.session = session
        self._capture_factory = capture_factory or self._open_capture
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._clock = session.clock
        self._utc_clock = utc_clock or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._thread = None
        self._preview = None
        self._photo_frame = None
        self._photo_at = None
        self._error = None
        self._last_ui = self._clock()
        self._stop_reason = None
        self._stop_at = None
        self._release_confirmed = True  # No outstanding capture handle before Start.
        self._release_error = None
        self._watchdog = None

    @staticmethod
    def _open_capture(index):
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        capture = cv2.VideoCapture(index, backend)
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        capture.set(cv2.CAP_PROP_FPS, 15)
        return capture

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive())

    @property
    def stopping(self):
        return self.running and self._stop.is_set()

    @property
    def release_confirmed(self):
        """Capture API release completed; not independent physical validation."""
        with self._lock:
            return self._release_confirmed and not self.running

    def start(self, index=0, *, segment_config=None):
        with self._lifecycle_lock:
            if self.running:
                return
            if self._release_error:
                raise RuntimeError("Previous capture release was not confirmed")
            now = self._clock()
            config = SegmentConfig() if segment_config is None else segment_config
            self.session.begin_segment(config, self._utc_clock(), now)
            # A fresh event isolates old watchdogs from a later camera run.
            stop = threading.Event()
            with self._lock:
                self._stop = stop
                self._last_ui = now
                self._error = None
                self._stop_reason = self._stop_at = None
                self._release_confirmed = False
                self._photo_frame = self._photo_at = None
            self._thread = threading.Thread(target=self._run, args=(index, stop), daemon=True, name="StressLens-camera")
            self._watchdog = threading.Thread(target=self._watch, args=(stop,), daemon=True, name="StressLens-deadline")
            try:
                self._thread.start()
                self._watchdog.start()
            except Exception:
                self._request_stop(stop, "capture_error", self._clock())
                raise

    def _remember_error(self, message):
        with self._lock:
            self._error = f"{self._error}; {message}" if self._error else str(message)

    def _request_stop(self, stop, reason, at):
        # Restart cannot replace the run between identity check and finalization,
        # including error publication. Never hold camera's lock across report
        # operations, or lifecycle's lock across a worker join.
        with self._lifecycle_lock:
            with self._lock:
                if stop is not self._stop or stop.is_set():
                    return
                self._stop_reason, self._stop_at = reason, at
                self._preview = None
                self._photo_frame = self._photo_at = None
                stop.set()
            try:
                self.session.finish_segment(reason, at)
            except Exception as exc:
                self._remember_error(f"Report finalization failed: {exc}")

    def _poll_limits(self, stop):
        if stop is not self._stop or stop.is_set():
            return True
        now = self._clock()
        deadline = self.session.segment_deadline()
        with self._lock:
            idle_end = self._last_ui + 20
        if deadline is not None and now >= deadline[0] and deadline[0] <= idle_end:
            self._request_stop(stop, deadline[1], deadline[0])
        elif now > idle_end:
            self._request_stop(stop, "inactivity", idle_end)
        elif deadline is not None and now >= deadline[0]:
            self._request_stop(stop, deadline[1], deadline[0])
        return stop.is_set()

    def _watch(self, stop):
        while not stop.wait(0.05):
            if self._poll_limits(stop) or not self.running:
                return

    def _run(self, index, stop):
        capture = None
        try:
            capture = self._capture_factory(index)
            if not capture.isOpened():
                raise RuntimeError("Camera unavailable. Close other camera apps, or try another camera index.")
            failures = 0
            while not self._poll_limits(stop):
                ok, frame = capture.read()
                if self._poll_limits(stop):
                    break
                if not ok:
                    failures += 1
                    if failures >= 10:
                        raise RuntimeError("Camera stopped supplying frames.")
                    stop.wait(0.1)
                    continue
                failures = 0
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                photo_at, photo_frame = self._clock(), rgb.copy()
                annotated = self.session.process(rgb, stop_requested=lambda: self._poll_limits(stop))
                if self._poll_limits(stop):
                    break
                ok, jpeg = cv2.imencode(".jpg", cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 80])
                if ok:
                    with self._lock:
                        if not stop.is_set():
                            self._preview = jpeg.tobytes()
                            self._photo_frame, self._photo_at = photo_frame, photo_at
                stop.wait(0.03)
        except Exception as exc:
            self._remember_error(str(exc))
            if not self._poll_limits(stop):
                self._request_stop(stop, "capture_error", self._clock())
        finally:
            if not stop.is_set():
                self._request_stop(stop, "capture_error", self._clock())
            try:
                if capture is not None:
                    capture.release()
                with self._lock:
                    self._release_confirmed = True
            except Exception as exc:
                with self._lock:
                    self._release_error = str(exc)
                    self._release_confirmed = False
                self._remember_error(f"Capture release failed: {exc}")
            try:
                self.session.stop(self._stop_reason or "capture_error", self._stop_at)
            except Exception as exc:
                self._remember_error(str(exc))
            with self._lock:
                self._preview = None
                self._photo_frame = self._photo_at = None

    def capture_photo(self):
        """Explicit still action: copy a fresh raw RGB frame, never open a device."""
        self._poll_limits(self._stop)
        with self._lock:
            age = None if self._photo_at is None else self._clock() - self._photo_at
            if (not self.running or self._stop.is_set() or self._error or self._photo_frame is None
                    or age is None or not 0 <= age <= 2):
                raise RuntimeError("No fresh camera frame is available. Start the camera yourself and wait for a fresh preview.")
            return self._photo_frame.copy()

    def preview(self):
        with self._lock:
            self._last_ui = self._clock()
            return self._preview, self._error

    def stop(self, reason="user_off"):
        with self._lifecycle_lock:
            stop, thread = self._stop, self._thread
            if not self._poll_limits(stop):
                self._request_stop(stop, reason, self._clock())
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        elif thread is None:
            self.session.stop(reason)

    def clear_report(self):
        with self._lifecycle_lock:
            if self.running or not self.release_confirmed:
                raise RuntimeError("Wait for confirmed capture release before Clear")
            self.session.clear_report()


def live_feedback(snapshot: dict) -> str:
    if snapshot.get("status") != "ok":
        return snapshot.get("message", "No current face reading.")
    changes = snapshot.get("changes", {})
    if changes:
        name, delta = max(changes.items(), key=lambda pair: abs(pair[1]))
        if abs(delta) >= 0.15:
            return f"{name} is {'higher' if delta > 0 else 'lower'} than your captured reference ({delta:+.2f} coefficient)."
        return "Measured facial shapes are close to your captured reference."
    groups = snapshot.get("groups", {})
    if groups:
        name, value = max(groups.items(), key=lambda pair: pair[1])
        return f"Largest current coefficient: {name.lower()} ({value:.2f}). Capture a reference to compare changes."
    return "Waiting for facial measurements."
