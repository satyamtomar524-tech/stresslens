"""Short computed descriptions; never convert measurements into stress diagnoses."""
import math


def analysis_overview(text, face, rating):
    wording = "No text was included."
    valid_text = False
    if text:
        probability = text.get("stress_probability")
        valid_text = (text.get("status") == "ok" and isinstance(probability, (int, float))
                      and not isinstance(probability, bool) and math.isfinite(probability) and 0 <= probability <= 1)
        wording = ("Your text contains stress-related language." if probability >= 0.5 else
                   "Your text uses less stress-related wording.") if valid_text else "A language result is unavailable for this text."
    if valid_text and face is None and rating is None:
        return wording + " No self-rating or photo/video was included."
    own = "Your self-rating was not provided" if rating is None else f"Your self-rating was {rating}/10 (your answer)"
    measured = "no photo/video was included"
    if face:
        status = face.get("status")
        count, total = face.get("face_frames"), face.get("frames_analyzed")
        valid = type(count) is int and type(total) is int and 0 <= count <= total and total > 0
        if status in {"no_face", "no_faces"} or (status == "ok" and valid and count == 0):
            measured = "no face was measured"
        elif status == "ok" and valid:
            measured = "facial movement was measured"
        else:
            measured = "photo/video analysis is unavailable for this input"
    return f"{wording} {own}; {measured}."


def work_overview(state, elapsed_seconds, summary):
    label = {"idle": "Not started", "working": "Working", "paused": "Paused", "ended": "Ended"}[state]
    seconds = max(0, int(elapsed_seconds))
    total = summary["total_checkins"]
    stress = sum(sum(row["stress_counts"].get(key, 0) for key in ("none", "low", "high"))
                 for row in summary["by_day"])
    clarity = sum(sum(row["clarity_counts"].get(key, 0) for key in ("clear", "mixed", "foggy"))
                  for row in summary["by_day"])
    return (f"{label}: {seconds // 60}m {seconds % 60:02d}s active work time. "
            f"Recorded check-ins: {total}; self-reported stress answered {stress}/{total} ({total - stress} missing), "
            f"clarity answered {clarity}/{total} ({total - clarity} missing).")


def report_overview(snapshot):
    total = len(snapshot.self_reports)
    answered = sum(row.state == "answered" for row in snapshot.self_reports)
    seconds = sum(segment.duration_seconds for segment in snapshot.segments)
    camera = "No camera observations have been finalized; no facial stress estimate is made."
    if snapshot.segments:
        valid = sum(segment.valid_slots for segment in snapshot.segments)
        expected = sum(segment.expected_slots for segment in snapshot.segments)
        windows = [window for segment in snapshot.segments for window in segment.facial_windows]
        if not valid:
            coverage = "no valid facial measurements were recorded"
        elif not any(window.usable for window in windows):
            coverage = "some facial samples were recorded, but coverage is too limited for a usable summary"
        elif valid < expected or not all(window.usable for window in windows):
            coverage = "facial measurements have gaps"
        else:
            coverage = "facial measurements are available"
        interrupted = "; a camera run was interrupted" if any(not segment.complete for segment in snapshot.segments) else ""
        camera = f"Finalized camera-on time: {seconds:g} s; {coverage}{interrupted}."
    return (f"Self-reported stress answers: {answered}/{total} ({total - answered} missing); "
            f"device readings supplied: {len(snapshot.measurements)}. {camera}")
