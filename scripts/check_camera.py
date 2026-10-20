"""Short real-hardware check. Keeps no images or recordings."""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from stresslens.live import LaptopCamera, LiveFaceSession


def main():
    parser = argparse.ArgumentParser(description=(
        "Check the laptop camera locally. MediaPipe sends technical usage/performance "
        "and system/media metadata to Google; inputs are processed on-device per Google."
    ))
    parser.add_argument("--allow-google-sdk-metrics", action="store_true",
                        help="Explicitly allow the face SDK metrics described above.")
    options = parser.parse_args()
    if not options.allow_google_sdk_metrics:
        parser.error("Camera check needs --allow-google-sdk-metrics after reviewing "
                     "https://developers.google.com/edge/mediapipe/legal/tos")
    camera = LaptopCamera(LiveFaceSession())
    camera.start()
    successes, statuses = 0, set()
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            preview, error = camera.preview()
            if error:
                raise RuntimeError(error)
            snapshot = camera.session.snapshot()
            statuses.add(snapshot["status"])
            if preview:
                successes += 1
            time.sleep(0.1)
        result = {"preview_polls_with_frames": successes, "processed_frames": snapshot["frames"],
                  "statuses_seen": sorted(statuses), "measurement_fps": snapshot["measurement_fps"],
                  "last_model_ms": snapshot.get("latency_ms"), "recordings_saved": 0}
        if not successes:
            raise RuntimeError("No camera frames received")
    finally:
        camera.stop()
    result["camera_released"] = not camera.running
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
