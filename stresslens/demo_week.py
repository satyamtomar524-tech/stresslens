"""Static fictional check-ins for an explicitly labeled example view only.

No person, recording or research archive supplied these invented points.
They demonstrate category counts, not a causal story or validated stress model.
"""

_POINTS = (
    ("2026-10-05T09:00:00Z", "answered", 0, "clear"),
    ("2026-10-05T15:00:00Z", "answered", 1, "mixed"),
    ("2026-10-06T09:00:00Z", "answered", 2, "foggy"),
    ("2026-10-06T15:00:00Z", "unsure", None, "unsure"),
    ("2026-10-07T09:00:00Z", "skipped", None, "skipped"),
    ("2026-10-07T15:00:00Z", "answered", 0, "mixed"),
    ("2026-10-08T09:00:00Z", "answered", 1, "clear"),
    ("2026-10-08T15:00:00Z", "answered", 2, "foggy"),
    ("2026-10-09T09:00:00Z", "unsure", None, "unsure"),
    ("2026-10-09T15:00:00Z", "answered", 1, "skipped"),
    ("2026-10-10T09:00:00Z", "answered", 2, "mixed"),
    ("2026-10-10T15:00:00Z", "skipped", None, "clear"),
    ("2026-10-11T09:00:00Z", "answered", 0, "foggy"),
    ("2026-10-11T15:00:00Z", "answered", 2, "unsure"),
)


def get_demo_week():
    """Return fresh JSON-compatible data, separate from any user's history.

    Exactly two invented point check-ins per UTC day. This function only
    builds the example; the application owns its visibly separate display.
    """
    return {
        "schema": "fictional-week/1",
        "is_fictional": True,
        "title": "Fictional week — example only",
        "start_date": "2026-10-05",
        "end_date": "2026-10-11",
        "records": [{
            "id": f"demo-week-{index:02d}",
            "answered_at": timestamp,
            "session_id": f"demo-week-{timestamp[:10]}",
            "stress_state": state,
            "stress_value": value,
            "clarity": clarity,
        } for index, (timestamp, state, value, clarity) in enumerate(_POINTS, 1)],
    }
