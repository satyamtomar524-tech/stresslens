"""Exercise test opt-in using a harmless sentinel suite, never the real SDK."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("allowed", [False, True])
def test_native_sdk_checks_require_explicit_metrics_choice(tmp_path, allowed):
    policy = Path(__file__).with_name("conftest.py")
    (tmp_path / "conftest.py").write_text(
        policy.read_text(encoding="utf-8") if policy.exists() else "",
        encoding="utf-8",
    )
    (tmp_path / "test_synthetic_policy.py").write_text("""
from pathlib import Path
import pytest

@pytest.mark.face_sdk
def test_synthetic_sdk_sentinel():
    Path("sentinel-ran").write_text("No SDK or camera is used in this fixture.")

def test_ordinary_check():
    assert 2 + 2 == 4
""", encoding="utf-8")
    options = ["--allow-google-sdk-metrics"] if allowed else []
    environment = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    environment.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q",
         "test_synthetic_policy.py", *options],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "sentinel-ran").exists() is allowed
    assert "PytestUnknownMarkWarning" not in result.stdout
    if not allowed:
        assert "1 skipped" in result.stdout
