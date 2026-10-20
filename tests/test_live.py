import inspect
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from stresslens.live import LiveFaceSession, LaptopCamera, live_feedback
from stresslens.session_report import ReportWorkspace, SegmentConfig, to_export

ROOT = Path(__file__).resolve().parents[1]


class Clock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        return self.value


def portrait():
    return cv2.cvtColor(cv2.imread(str(ROOT / "assets/sample_face.jpg")), cv2.COLOR_BGR2RGB)


@pytest.mark.face_sdk
def test_actual_continuous_model_reference_and_loss_of_face():
    clock = Clock()
    session = LiveFaceSession(clock=clock)
    image = portrait()
    session.capture_reference(seconds=1)
    try:
        for i in range(13):
            clock.value = i * 0.1
            processed = session.process(image)
        result = session.snapshot()
        assert result["status"] == "ok"
        assert result["frames"] == 13
        assert result["baseline"]
        assert all(abs(delta) < 0.1 for delta in result["changes"].values())
        assert "close to" in live_feedback(result)
        assert processed.shape == image.shape
        assert result["measurement_fps"] > 5
        assert "stress_score" not in result
        assert "Reference captured" in result["reference_message"]
        session.clear_reference()
        assert not session.snapshot()["baseline"]
        assert "reference_message" not in session.snapshot()
        session.capture_reference(seconds=1)
        assert "reference_progress" in session.snapshot()
        assert "reference_message" not in session.snapshot()
        session.clear_reference()
        clock.value += 0.1
        session.process(np.zeros_like(image))
        lost = session.snapshot()
        assert lost["status"] == "no_face"
        assert not lost["groups"] and not lost["changes"]
        assert all(lost["history"][-1][name] is None for name in result["groups"])
    finally:
        session.stop()
    assert session.snapshot()["status"] == "stopped"
    assert session.snapshot()["history"] == []


@pytest.mark.face_sdk
def test_stale_stream_has_no_current_reading():
    clock = Clock()
    session = LiveFaceSession(clock=clock)
    try:
        session.process(portrait())
        clock.value = 3
        result = session.snapshot()
        assert result["status"] == "stale"
        assert not result["groups"] and not result["changes"]
    finally:
        session.stop()


def test_no_face_and_multiple_faces_do_not_create_reference(mock_face_sdk):
    clock = Clock()
    detector = SimpleNamespace(detect_for_video=lambda image, timestamp: SimpleNamespace(face_landmarks=[[], []]), close=lambda: None)
    session = LiveFaceSession(detector_factory=lambda: detector, clock=clock)
    session.capture_reference(seconds=1)
    for i in range(13):
        clock.value = i * 0.1
        session.process(np.zeros((200, 200, 3), dtype=np.uint8))
    result = session.snapshot()
    assert result["status"] == "multiple_faces"
    assert not result["baseline"]
    assert "failed" in result["reference_message"]
    session.stop()


def test_model_failure_is_reported_and_releases_resources(mock_face_sdk):
    def fail():
        raise RuntimeError("Test model failure")
    session = LiveFaceSession(detector_factory=fail)
    session.process(np.zeros((200, 200, 3), dtype=np.uint8))
    assert session.snapshot()["status"] == "error"
    assert "Test model failure" in session.snapshot()["message"]
    session.stop()


def test_live_feedback_describes_measured_change_without_diagnosis():
    message = live_feedback({"status": "ok", "changes": {"Brow lowering": 0.3, "Smile shape": 0.05}})
    assert "Brow lowering is higher" in message
    assert "stress" not in message.lower()
    assert live_feedback({"status": "no_face", "message": "No face"}) == "No face"


@pytest.mark.face_sdk
def test_camera_worker_processes_frames_and_stop_releases_device():
    class Capture:
        released = False

        def isOpened(self):
            return True

        def read(self):
            return True, cv2.resize(cv2.imread(str(ROOT / "assets/sample_face.jpg")), (410, 512))

        def release(self):
            self.released = True

    capture = Capture()
    camera = LaptopCamera(LiveFaceSession(), capture_factory=lambda index: capture)
    try:
        camera.start()
        deadline = time.monotonic() + 10
        preview = None
        while not preview and time.monotonic() < deadline:
            preview, error = camera.preview()
            assert error is None
            time.sleep(0.05)
        assert preview
        assert cv2.imdecode(np.frombuffer(preview, dtype=np.uint8), cv2.IMREAD_COLOR) is not None
        assert camera.session.snapshot()["frames"] > 0
    finally:
        camera.stop()
    assert capture.released
    assert not camera.running
    assert camera.preview()[0] is None
    assert camera.session.snapshot()["status"] == "stopped"


def test_camera_unavailable_reports_error_without_running():
    capture = SimpleNamespace(isOpened=lambda: False, release=lambda: None)
    camera = LaptopCamera(LiveFaceSession(), capture_factory=lambda index: capture)
    camera.start()
    camera._thread.join(timeout=3)
    assert not camera.running
    assert "Camera unavailable" in camera.preview()[1]


def test_stop_keeps_stalled_worker_pending_and_discards_its_late_frame(mock_face_sdk):
    blocked = threading.Event()
    resume = threading.Event()
    timestamps = []

    class Capture:
        reads = 0
        released = False

        def isOpened(self):
            return True

        def read(self):
            self.reads += 1
            if self.reads > 1:
                blocked.set()
                resume.wait(10)
            return True, np.zeros((40, 40, 3), dtype=np.uint8)

        def release(self):
            self.released = True

    def detect(image, timestamp):
        timestamps.append(timestamp)
        return SimpleNamespace(face_landmarks=[])

    detector = SimpleNamespace(detect_for_video=detect, close=lambda: None)
    session = LiveFaceSession(detector_factory=lambda: detector)
    capture = Capture()
    camera = LaptopCamera(session, capture_factory=lambda index: capture)
    camera.start()
    try:
        assert blocked.wait(3)
        assert camera.preview()[0] is not None
        camera.stop()
        assert camera.running, "A stop request must not hide an unreleased worker."
        assert camera.stopping
        assert camera.preview()[0] is None
        worker = camera._thread
        camera.start()
        assert camera._thread is worker
        assert not capture.released
    finally:
        resume.set()
        camera._thread.join(3)
    assert not camera.running
    assert not camera.stopping
    assert capture.released
    assert camera.preview()[0] is None
    assert session.snapshot()["status"] == "stopped"
    assert len(timestamps) == 1, "The frame returned after Stop must never reach inference."


def detector_with_failures(failed_timestamps):
    def detect(image, timestamp):
        if timestamp in failed_timestamps:
            raise RuntimeError("Synthetic transient model error")
        return SimpleNamespace(
            face_landmarks=[[SimpleNamespace(x=0.2, y=0.5, z=0.0), SimpleNamespace(x=0.8, y=0.5, z=0.0)]],
            face_blendshapes=[[SimpleNamespace(category_name="jawOpen", score=0.2)]],
            facial_transformation_matrixes=[],
        )
    return SimpleNamespace(detect_for_video=detect, close=lambda: None)


def test_transient_model_error_preserves_a_null_history_sample(mock_face_sdk):
    clock = Clock()
    session = LiveFaceSession(detector_factory=lambda: detector_with_failures({200}), clock=clock)
    try:
        for now in [0.0, 0.2, 0.4]:
            clock.value = now
            session.process(np.zeros((40, 40, 3), dtype=np.uint8))
        result = session.snapshot()
        assert result["status"] == "ok"
        assert [row["seconds"] for row in result["history"]] == [0.0, 0.2, 0.4]
        assert result["history"][1] == {"seconds": 0.2, "Brow lowering": None, "Eye narrowing": None,
                                        "Lip pressing": None, "Smile shape": None, "Eye closure": None, "Jaw opening": None}
        assert result["history"][0]["Jaw opening"] == 0.2
        assert result["history"][2]["Jaw opening"] == 0.2
    finally:
        session.stop()


def test_reference_coverage_counts_failed_model_attempts(mock_face_sdk):
    clock = Clock()
    session = LiveFaceSession(detector_factory=lambda: detector_with_failures({200, 800}), clock=clock)
    session.capture_reference(seconds=1.2)
    try:
        for now in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2]:
            clock.value = now
            session.process(np.zeros((40, 40, 3), dtype=np.uint8))
        result = session.snapshot()
        assert result["baseline"] is None, "Five valid samples out of seven attempts must fail the 80% coverage check."
        assert "failed" in result["reference_message"].lower()
        assert "reference_progress" not in result
    finally:
        session.stop()


LIFECYCLE_UTC = datetime(2026, 1, 1, 12, tzinfo=UTC)


def lifecycle_session(clock, workspace=None, detector_factory=None):
    assert "report_workspace" in inspect.signature(LiveFaceSession).parameters, "Report lifecycle attachment not implemented"
    workspace = workspace if workspace is not None else ReportWorkspace(clock=clock)
    session = LiveFaceSession(clock=clock, report_workspace=workspace,
                              detector_factory=detector_factory or (lambda: detector_with_failures(set())))
    return session, workspace


def lifecycle_wait(predicate, timeout=2):
    end = time.monotonic() + timeout
    while not predicate() and time.monotonic() < end:
        time.sleep(0.01)
    assert predicate(), "Synthetic lifecycle condition did not settle"


class LifecycleCapture:
    def __init__(self, reader=lambda n: (False, None), opened=True, release_error=False):
        self.reader, self.opened, self.release_error = reader, opened, release_error
        self.reads = self.release_calls = 0
        self.released = False

    def isOpened(self):
        return self.opened

    def read(self):
        self.reads += 1
        return self.reader(self.reads)

    def release(self):
        self.release_calls += 1
        if self.release_error:
            raise RuntimeError("synthetic release failed")
        self.released = True


def lifecycle_stop(camera, unblock, reason="user_off"):
    stopper = threading.Thread(target=lambda: camera.stop(reason=reason))
    stopper.start()
    lifecycle_wait(lambda: camera.stopping)
    unblock.set()
    stopper.join(4)
    assert not stopper.is_alive()


def test_lifecycle_explicit_anchor_counts_open_delay_and_only_actual_events(mock_face_sdk):
    clock = Clock()
    session, workspace = lifecycle_session(clock)
    session.begin_segment(SegmentConfig(), LIFECYCLE_UTC, 0)
    clock.value = 2
    session.process(np.zeros((40, 40, 3), dtype=np.uint8))
    for _ in range(5):
        session.snapshot()
    clock.value = 3
    session.stop()
    report = workspace.snapshot().segments[0]
    assert (report.duration_seconds, report.expected_slots, report.valid_slots) == (3, 30, 1)
    assert report.sampling_hz == pytest.approx(1 / 3)
    assert report.max_gap_seconds == pytest.approx(2)
    assert session.snapshot()["history"] == []


def test_lifecycle_open_failure_has_an_anchored_interrupted_report():
    clock = Clock()
    session, workspace = lifecycle_session(clock)
    capture = LifecycleCapture(opened=False)
    observed = []

    def open_capture(index):
        observed.append(workspace.snapshot().active_segment_id)
        clock.value = 2
        return capture

    camera = LaptopCamera(session, capture_factory=open_capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    camera._thread.join(2)
    assert observed[0] is not None
    report = workspace.snapshot().segments[0]
    assert (report.duration_seconds, report.reason, report.valid_slots) == (2, "capture_error", 0)
    assert not report.complete and capture.released


@pytest.mark.parametrize("kind", ["no_face", "multiple_faces", "too_far", "error"])
def test_lifecycle_unavailable_processing_still_reaches_timer(kind, mock_face_sdk):
    clock = Clock()

    def detect(image, timestamp):
        if kind == "error":
            raise RuntimeError("synthetic model failure")
        points = [SimpleNamespace(x=0.2, y=0.5, z=0), SimpleNamespace(x=0.25, y=0.5, z=0)]
        faces = [] if kind == "no_face" else ([[], []] if kind == "multiple_faces" else [points])
        return SimpleNamespace(face_landmarks=faces, face_blendshapes=[], facial_transformation_matrixes=[])

    detector = SimpleNamespace(detect_for_video=detect, close=lambda: None)
    session, workspace = lifecycle_session(clock, detector_factory=lambda: detector)

    def read(n):
        clock.value = n / 10
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start(segment_config=SegmentConfig(1))
    camera._thread.join(3)
    assert not camera.running and capture.released
    report = workspace.snapshot().segments[0]
    assert (report.reason, report.duration_seconds, report.valid_slots) == ("timer_end", 1, 0)
    assert dict(report.facial_windows[0].reason_counts).get(kind, 0) > 0


@pytest.mark.parametrize("timer,step,reason,duration", [(1, 0.2, "timer_end", 1), (None, 0.1, "capture_error", 1)])
def test_lifecycle_read_failures_do_not_bypass_deadline(timer, step, reason, duration):
    clock = Clock()
    session, workspace = lifecycle_session(clock)

    def read(n):
        clock.value = n * step
        return False, None

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start(segment_config=SegmentConfig(timer))
    camera._thread.join(3)
    assert not camera.running and capture.released
    report = workspace.snapshot().segments[0]
    assert (report.reason, report.duration_seconds, report.valid_slots) == (reason, duration, 0)


@pytest.mark.parametrize("timer,jump,reason,duration", [(2, 2, "timer_end", 2), (None, 21, "inactivity", 20)])
def test_lifecycle_stalled_read_finalizes_without_claiming_release(timer, jump, reason, duration):
    clock = Clock()
    session, workspace = lifecycle_session(clock)
    entered, unblock = threading.Event(), threading.Event()

    def read(n):
        entered.set()
        unblock.wait(4)
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start(segment_config=SegmentConfig(timer))
    try:
        assert entered.wait(1)
        clock.value = jump
        lifecycle_wait(lambda: camera.stopping)
        lifecycle_wait(lambda: len(workspace.snapshot().segments) == 1)
        report = workspace.snapshot().segments[0]
        assert (report.reason, report.duration_seconds, report.valid_slots) == (reason, duration, 0)
        assert camera.running and not camera.release_confirmed and not capture.released
        worker = camera._thread
        camera.start()
        assert camera._thread is worker and len(workspace.snapshot().segments) == 1
        with pytest.raises(RuntimeError):
            camera.clear_report()
    finally:
        unblock.set()
        camera._thread.join(3)
    assert capture.released and camera.release_confirmed and not camera.running
    assert session.snapshot()["frames"] == 0 and camera.preview()[0] is None
    camera.clear_report()
    assert workspace.snapshot().segments == ()


@pytest.mark.parametrize("reason", ["user_off", "consent_revoked"])
def test_lifecycle_stop_before_first_frame_uses_requested_reason(reason):
    clock = Clock()
    session, workspace = lifecycle_session(clock)
    entered, unblock = threading.Event(), threading.Event()

    def read(n):
        entered.set()
        unblock.wait(4)
        return False, None

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    try:
        assert entered.wait(1)
        clock.value = 0.5
        lifecycle_stop(camera, unblock, reason)
    finally:
        unblock.set()
        camera.stop(reason=reason)
    report = workspace.snapshot().segments[0]
    assert (report.reason, report.duration_seconds, report.expected_slots, report.valid_slots) == (reason, 0.5, 5, 0)
    assert capture.released and camera.release_confirmed


def test_lifecycle_off_on_retains_reports_and_isolates_reference(mock_face_sdk):
    clock = Clock()
    session, workspace = lifecycle_session(clock)
    image = np.zeros((40, 40, 3), dtype=np.uint8)
    session.begin_segment(SegmentConfig(), LIFECYCLE_UTC, 0)
    session.capture_reference(seconds=1)
    for now in [0, 0.2, 0.4, 0.6, 0.8, 1]:
        clock.value = now
        session.process(image)
    clock.value = 2
    session.stop()
    first = workspace.snapshot().segments[0]
    assert first.reference is not None
    clock.value = 10
    session.begin_segment(SegmentConfig(), LIFECYCLE_UTC + timedelta(seconds=10), 10)
    assert session.snapshot()["baseline"] is None
    clock.value = 10.2
    session.process(image)
    clock.value = 11
    session.stop()
    snapshot = workspace.snapshot()
    assert snapshot.segments[0] is first
    assert snapshot.segments[1].reference is None
    assert snapshot.segments[0].segment_id != snapshot.segments[1].segment_id
    payload = to_export(snapshot)
    assert payload["session"]["camera_on_seconds"] == 3
    assert payload["off_camera_periods"][0]["duration_seconds"] == 8


def test_lifecycle_resource_cap_with_heartbeat_uses_shared_clock(mock_face_sdk):
    clock = Clock()
    detector = SimpleNamespace(detect_for_video=lambda image, timestamp: SimpleNamespace(
        face_landmarks=[], face_blendshapes=[], facial_transformation_matrixes=[]), close=lambda: None)
    session, workspace = lifecycle_session(clock, detector_factory=lambda: detector)

    def read(n):
        clock.value = min(3600, n * 19)
        camera.preview()  # Synthetic UI heartbeat at <20-second intervals.
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    camera._thread.join(10)
    assert not camera.running and capture.released
    report = workspace.snapshot().segments[0]
    assert (report.reason, report.duration_seconds, len(report.facial_windows)) == ("resource_limit", 3600, 180)


@pytest.mark.parametrize("failure", ["finalize", "release", "detector_close"])
def test_lifecycle_cleanup_attempts_all_resources_despite_exceptions(failure, mock_face_sdk):
    class FailingWorkspace(ReportWorkspace):
        def finish_segment(self, elapsed_seconds, reason):
            raise RuntimeError("synthetic finalization failed")

    clock = Clock()
    workspace = FailingWorkspace(clock=clock) if failure == "finalize" else ReportWorkspace(clock=clock)
    close_attempts = []
    detector = detector_with_failures(set())

    def close():
        close_attempts.append(True)
        if failure == "detector_close":
            raise RuntimeError("synthetic detector close failed")

    detector.close = close
    session, workspace = lifecycle_session(clock, workspace, lambda: detector)

    def read(n):
        clock.value = n / 10
        if n > 1:
            raise RuntimeError("synthetic capture failed")
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    capture = LifecycleCapture(read, release_error=failure == "release")
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    camera._thread.join(3)
    assert not camera.running and capture.release_calls == 1 and close_attempts == [True]
    assert session.snapshot()["history"] == [] and session.snapshot()["groups"] == {}
    assert camera.preview()[1]
    if failure == "finalize":
        assert workspace.snapshot().active_segment_id is not None and session.report_error
        assert workspace.snapshot().segments == ()
    else:
        assert len(workspace.snapshot().segments) == 1
    if failure == "release":
        assert not camera.release_confirmed
        with pytest.raises(RuntimeError):
            camera.start()
        with pytest.raises(RuntimeError):
            camera.clear_report()


def test_lifecycle_concurrent_stops_finalize_once():
    class CountWorkspace(ReportWorkspace):
        finish_calls = 0

        def finish_segment(self, elapsed_seconds, reason):
            self.finish_calls += 1
            return super().finish_segment(elapsed_seconds, reason)

    clock = Clock()
    workspace = CountWorkspace(clock=clock)
    session, workspace = lifecycle_session(clock, workspace)
    entered, unblock = threading.Event(), threading.Event()

    def read(n):
        entered.set()
        unblock.wait(4)
        return False, None

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    assert entered.wait(1)
    clock.value = 0.5
    stops = [threading.Thread(target=camera.stop) for _ in range(2)]
    for stopper in stops:
        stopper.start()
    lifecycle_wait(lambda: camera.stopping)
    unblock.set()
    for stopper in stops:
        stopper.join(4)
        assert not stopper.is_alive()
    assert workspace.finish_calls == 1 and len(workspace.snapshot().segments) == 1
    assert capture.release_calls == 1 and camera.release_confirmed


def test_lifecycle_capacity_rejection_does_not_open_capture():
    clock = Clock()
    workspace = ReportWorkspace(clock=clock)
    for _ in range(10):
        workspace.start_segment(SegmentConfig(), LIFECYCLE_UTC, 0)
        workspace.finish_segment(0, "user_off")
    session, workspace = lifecycle_session(clock, workspace)
    opened = []
    camera = LaptopCamera(session, capture_factory=lambda index: opened.append(index), utc_clock=lambda: LIFECYCLE_UTC)
    before = workspace.snapshot()
    with pytest.raises(ValueError):
        camera.start()
    assert not opened and not camera.running and workspace.snapshot() == before


@pytest.mark.parametrize("phase", ["conversion", "detector"])
def test_lifecycle_processing_cutoff_rejects_results_after_idle_deadline(phase, mock_face_sdk, monkeypatch):
    # Force the worker to enforce the boundary before the watchdog gets CPU.
    monkeypatch.setattr(LaptopCamera, "_watch", lambda self, stop: stop.wait(3))
    clock = Clock()
    model_calls = []
    detector = detector_with_failures(set())
    original_detect = detector.detect_for_video

    def detect(image, timestamp):
        model_calls.append(timestamp)
        if phase == "detector":
            clock.value = 20.1
        return original_detect(image, timestamp)

    detector.detect_for_video = detect
    original_convert = cv2.cvtColor

    def convert(image, conversion):
        if phase == "conversion" and conversion == cv2.COLOR_BGR2RGB:
            clock.value = 20.1
        return original_convert(image, conversion)

    monkeypatch.setattr(cv2, "cvtColor", convert)
    session, workspace = lifecycle_session(clock, detector_factory=lambda: detector)

    def read(n):
        clock.value = 19.9
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    capture = LifecycleCapture(read)
    camera = LaptopCamera(session, capture_factory=lambda index: capture, utc_clock=lambda: LIFECYCLE_UTC)
    camera.start()
    camera._thread.join(2)
    assert not camera.running and capture.released
    assert len(workspace.snapshot().segments) == 1 and session.report_error is None
    report = workspace.snapshot().segments[0]
    assert (report.reason, report.duration_seconds, report.valid_slots) == ("inactivity", 20, 0)
    assert len(model_calls) == (0 if phase == "conversion" else 1)


@pytest.mark.parametrize("with_report", [True, False], ids=["report", "legacy"])
@pytest.mark.parametrize("late_error", [False, True], ids=["finalize", "error"])
def test_lifecycle_stale_watchdog_cannot_affect_restart(with_report, late_error, mock_face_sdk, monkeypatch):
    clock = Clock()
    workspace = ReportWorkspace(clock=clock) if with_report else None
    session = LiveFaceSession(detector_factory=lambda: detector_with_failures(set()),
                              clock=clock, report_workspace=workspace)
    a_read, release_a = threading.Event(), threading.Event()
    b_read, release_b = threading.Event(), threading.Event()
    b_next, release_b_next = threading.Event(), threading.Event()
    callback_paused, resume_callback = threading.Event(), threading.Event()
    restart_at_lock = threading.Event()
    restart_waited, restart_errors = [], []

    class ObservedLifecycleLock:
        """Observe a real acquire; do not require restart through a held lock."""
        def __init__(self):
            self.lock = threading.RLock()

        def __enter__(self):
            if threading.current_thread().name == "StressLens-restart-regression":
                acquired = self.lock.acquire(blocking=False)
                restart_waited.append(not acquired)
                restart_at_lock.set()
                if not acquired:
                    self.lock.acquire()
            else:
                self.lock.acquire()
            return self

        def __exit__(self, *args):
            self.lock.release()

    def read_a(n):
        a_read.set()
        assert release_a.wait(8)
        return False, None

    def read_b(n):
        entered, release = (b_read, release_b) if n == 1 else (b_next, release_b_next)
        entered.set()
        assert release.wait(8)
        return True, np.zeros((40, 40, 3), dtype=np.uint8)

    captures = [LifecycleCapture(read_a), LifecycleCapture(read_b)]
    camera = LaptopCamera(session, capture_factory=lambda index: captures.pop(0),
                          utc_clock=lambda: LIFECYCLE_UTC + timedelta(seconds=clock()))
    camera._lifecycle_lock = ObservedLifecycleLock()
    original_finish = session.finish_segment
    old_watchdog = None

    def paused_finish(reason="user_off", now=None):
        if threading.current_thread() is old_watchdog:
            callback_paused.set()  # A event is already set; report call has not run.
            assert resume_callback.wait(8)
            if late_error:
                raise RuntimeError("synthetic delayed A finalization error")
        return original_finish(reason, now)

    monkeypatch.setattr(session, "finish_segment", paused_finish)

    def restart():
        try:
            camera.start(segment_config=SegmentConfig(5))
        except Exception as exc:
            restart_errors.append(exc)

    starter = threading.Thread(target=restart, name="StressLens-restart-regression")
    try:
        camera.start()
        old_worker, old_watchdog, a_event = camera._thread, camera._watchdog, camera._stop
        assert a_read.wait(2)
        clock.value = 20.1
        assert callback_paused.wait(2)
        assert a_event.is_set()
        release_a.set()
        old_worker.join(2)
        assert not old_worker.is_alive() and camera.release_confirmed
        a_report = workspace.snapshot().segments[0] if with_report else None
        clock.value = 21
        starter.start()
        assert restart_at_lock.wait(2)
        if restart_waited == [False]:
            # Old code can start B here. A synchronized fix may keep it waiting.
            assert b_read.wait(2)
        resume_callback.set()
        old_watchdog.join(2)
        starter.join(2)
        assert not old_watchdog.is_alive() and not starter.is_alive()
        assert not restart_errors and b_read.wait(2)
        assert camera.running and camera._stop is not a_event and not camera._stop.is_set()
        assert camera._stop_reason is None and camera._stop_at is None
        assert camera.preview()[1] is None and session.report_error is None
        if with_report:
            snapshot = workspace.snapshot()
            b_id = snapshot.active_segment_id
            assert b_id is not None and b_id != a_report.segment_id
            assert snapshot.segments == (a_report,)
            assert session.segment_deadline() == (26, "timer_end")
        else:
            assert session.segment_deadline() is None
        clock.value = 21.1
        release_b.set()
        assert b_next.wait(2)  # B accepted its first valid observation.
        assert session.snapshot()["frames"] == 1
        assert session.snapshot()["history"][-1]["seconds"] == pytest.approx(0.1 if with_report else 0)
        clock.value = 22
        lifecycle_stop(camera, release_b_next)
        assert camera.release_confirmed and camera.preview()[1] is None
        if with_report:
            reports = workspace.snapshot().segments
            assert len(reports) == 2 and reports[0] is a_report
            assert (a_report.reason, a_report.duration_seconds) == ("inactivity", 20)
            b_report = reports[1]
            assert b_report.segment_id == b_id
            assert (b_report.reason, b_report.duration_seconds, b_report.expected_slots,
                    b_report.valid_slots) == ("user_off", 1, 10, 1)
    finally:
        resume_callback.set()
        release_a.set()
        release_b.set()
        release_b_next.set()
        if starter.ident is not None:
            starter.join(2)
        camera.stop()
        if old_watchdog is not None:
            old_watchdog.join(2)
