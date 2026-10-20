"""The unopened app must not load the native face SDK before user opt-in."""
import subprocess
import sys
from pathlib import Path


def test_default_app_does_not_load_mediapipe():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", """
import sys
from streamlit.testing.v1 import AppTest
app = AppTest.from_file(sys.argv[1], default_timeout=60).run()
assert not app.exception, app.exception
assert 'mediapipe' not in sys.modules, 'Default page loaded the native face SDK'
""", str(root / "app.py")],
        cwd=root, capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
