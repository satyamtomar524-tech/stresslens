"""Presentation of existing camera state; no capture, consent or timing changes."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class LiveStatus:
    state: str
    title: str
    message: str
    start_hint: str = ""
    freshness: str = ""
    current: bool = False


def live_status(snapshot, *, running, stopping, released, consented, error=None, last_reason=None):
    if stopping or (running and not consented) or (not running and not released):
        return LiveStatus(
            "stopping", "Finishing your session",
            "Stopping capture. Start unavailable: device release is unconfirmed. "
            "Restart, Clear and downloads wait; numeric data is retained.",
        )
    if not consented:
        return LiveStatus(
            "off", "Camera is off",
            "Start unavailable: face features are off. Choose Review camera privacy to review the SDK choice. "
            "Text and check-ins remain available.",
        )
    if not running:
        message = "Press Start camera when you want a new observation."
        if last_reason == "inactivity":
            message = "Paused after 20 seconds without page updates. " + message
        if error:
            message = "The previous capture failed. " + message
        return LiveStatus("off", "Camera is off", message)

    age = snapshot.get("frame_age_seconds")
    known_age = type(age) in (int, float) and math.isfinite(age) and age >= 0
    freshness = (f"Last frame received {age:.1f} seconds ago; frame receipt does not establish usable face data."
                 if known_age else "Frame freshness is unavailable.")
    start_hint = "Start unavailable: a camera session is already active."
    if snapshot.get("status") == "ok" and snapshot.get("groups") and known_age and age <= 2:
        return LiveStatus("collecting", "Collecting facial movement",
                          "One face tracked; facial movement measured.", start_hint, freshness, True)
    if snapshot.get("status") == "waiting" and not known_age:
        return LiveStatus("starting", "Starting your session", "Opening camera and loading the face model…",
                          start_hint, freshness)
    if known_age and age > 2:
        message = "No current reading; the last frame is stale."
    elif snapshot.get("status") == "ok":
        message = ("No usable facial movement coefficients are available." if known_age else
                   "A current usable observation is not established without frame freshness.")
    else:
        message = snapshot.get("message", "Waiting for one clear face; no current movement coefficients.")
    return LiveStatus("unavailable", "No usable facial observation", message, start_hint, freshness)
