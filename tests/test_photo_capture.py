"""Real LaptopCamera adapter with a synthetic reader/processor; no webcam/SDK."""
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from stresslens.live import LaptopCamera


class Session:
    def __init__(self, clock):
        self.clock = lambda: clock.value

    def begin_segment(self, *args):
        pass

    def segment_deadline(self):
        return None

    def process(self, rgb, stop_requested):
        # Simulate annotation mutating its input: selected still must be raw.
        rgb[:] = 0
        return rgb

    def finish_segment(self, *args):
        pass

    def stop(self, *args):
        pass


class Reader:
    def __init__(self, *, first_blocked=False):
        self.calls = 0
        self.entered = threading.Event()
        self.release_read = threading.Event()
        self.first_blocked = first_blocked

    def isOpened(self):
        return True

    def read(self):
        self.calls += 1
        if self.calls > 1 or self.first_blocked:
            self.entered.set()
            self.release_read.wait(4)
        return True, np.full((6, 8, 3), (20, 40, 80), dtype=np.uint8)

    def release(self):
        pass


def wait_for(predicate):
    end = time.monotonic() + 2
    while not predicate() and time.monotonic() < end:
        time.sleep(0.01)
    assert predicate(), "Synthetic worker did not reach its expected boundary"


def test_snapshot_never_starts_a_stopped_camera():
    def forbidden(index):
        raise AssertionError("A still snapshot must not open a camera")
    camera = LaptopCamera(Session(SimpleNamespace(value=0)), capture_factory=forbidden)
    with pytest.raises(RuntimeError):
        camera.capture_photo()
    assert not camera.running


def test_snapshot_is_raw_detached_and_rejects_stale_or_stopped_frames():
    clock, reader = SimpleNamespace(value=0.0), Reader()
    camera = LaptopCamera(Session(clock), capture_factory=lambda index: reader)
    try:
        camera.start()
        wait_for(lambda: camera.preview()[0] is not None)
        photo = camera.capture_photo()
        assert photo[0, 0].tolist() == [80, 40, 20]
        photo[:] = 255
        assert camera.capture_photo()[0, 0].tolist() == [80, 40, 20]
        wait_for(reader.entered.is_set)
        clock.value = 3.0
        with pytest.raises(RuntimeError):
            camera.capture_photo()
    finally:
        reader.release_read.set()
        camera.stop()
    with pytest.raises(RuntimeError):
        camera.capture_photo()


def test_snapshot_rejects_starting_and_stopping_without_returning_old_preview():
    clock, reader = SimpleNamespace(value=0.0), Reader(first_blocked=True)
    camera = LaptopCamera(Session(clock), capture_factory=lambda index: reader)
    stopper = None
    try:
        camera.start()
        wait_for(reader.entered.is_set)
        with pytest.raises(RuntimeError):
            camera.capture_photo()
        stopper = threading.Thread(target=camera.stop)
        stopper.start()
        wait_for(lambda: camera.stopping)
        with pytest.raises(RuntimeError):
            camera.capture_photo()
    finally:
        reader.release_read.set()
        if stopper:
            stopper.join(4)
        camera.stop()
