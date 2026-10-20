"""Download Google's official face model once; runtime inference stays local."""
import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"


def main():
    folder = ROOT / "models"
    folder.mkdir(exist_ok=True)
    target = folder / "face_landmarker.task"
    if not target.exists():
        request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "StressLens-research/1.0"})
        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read(20 * 1024 * 1024)
        if len(data) < 1_000_000 or len(data) >= 20 * 1024 * 1024:
            raise RuntimeError("Unexpected face-model download size.")
        temporary = target.with_suffix(".download")
        temporary.write_bytes(data)
        temporary.replace(target)
    manifest = {"name": "Google MediaPipe Face Landmarker", "version": "float16/1",
                "source": MODEL_URL, "bytes": target.stat().st_size,
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "purpose": "Face landmarks and blendshape coefficients; not stress prediction"}
    (folder / "face_model_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
