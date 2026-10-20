"""The developer camera helper must require an explicit SDK-metrics choice."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def helper():
    path = Path(__file__).resolve().parents[1] / "scripts" / "check_camera.py"
    spec = importlib.util.spec_from_file_location("camera_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_camera_helper_without_metrics_flag_never_opens_camera(monkeypatch):
    module = helper()
    starts = []
    camera = SimpleNamespace(start=lambda: starts.append(True), stop=lambda: None,
                             preview=lambda: (None, "Synthetic camera error"))
    monkeypatch.setattr(module, "LaptopCamera", lambda session: camera)
    monkeypatch.setattr(module.sys, "argv", ["check_camera.py"])
    with pytest.raises(SystemExit) as result:
        module.main()
    assert result.value.code == 2
    assert starts == []


def test_camera_helper_with_explicit_flag_uses_only_fake_hardware(monkeypatch):
    module = helper()
    starts, stops = [], []
    camera = SimpleNamespace(start=lambda: starts.append(True), stop=lambda: stops.append(True),
                             preview=lambda: (None, "Synthetic camera error"))
    monkeypatch.setattr(module, "LaptopCamera", lambda session: camera)
    monkeypatch.setattr(module.sys, "argv", ["check_camera.py", "--allow-google-sdk-metrics"])
    with pytest.raises(RuntimeError, match="Synthetic camera error"):
        module.main()
    assert starts == [True]
    assert stops == [True]
