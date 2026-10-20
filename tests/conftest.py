"""Keep routine checks separate from real MediaPipe SDK metrics consent."""
import sys
from types import SimpleNamespace

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--allow-google-sdk-metrics",
        action="store_true",
        default=False,
        help="Run real MediaPipe SDK checks; its metrics may be sent to Google.",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "face_sdk: initializes the real MediaPipe SDK (explicit metrics choice required)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--allow-google-sdk-metrics"):
        return
    blocked = pytest.mark.skip(
        reason="Real face SDK metrics require --allow-google-sdk-metrics; review README first.",
    )
    for item in items:
        if item.get_closest_marker("face_sdk"):
            item.add_marker(blocked)


@pytest.fixture
def mock_face_sdk(monkeypatch):
    """Only replace the image wrapper for already simulated detector tests.

    This does not emulate or validate MediaPipe detection. An accidental real
    detector call fails: the fixture deliberately has no SDK tasks namespace.
    """
    class SyntheticSDKImage:
        def __init__(self, *, image_format, data):
            if image_format != "synthetic-srgb":
                raise ValueError("Synthetic fixture expects the declared image format.")
            self._data = data

        def numpy_view(self):
            return self._data

    monkeypatch.setitem(sys.modules, "mediapipe", SimpleNamespace(
        Image=SyntheticSDKImage,
        ImageFormat=SimpleNamespace(SRGB="synthetic-srgb"),
    ))
