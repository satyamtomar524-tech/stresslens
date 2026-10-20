"""Pure descriptive counts of point check-ins; no inference, storage or clock."""
from collections.abc import Mapping
from datetime import UTC, datetime

_FIELDS = ("id", "answered_at", "session_id", "stress_state", "stress_value", "clarity")
_STRESS = ("none", "low", "high", "unsure", "skipped", "expired")
_CLARITY = ("clear", "mixed", "foggy", "unsure", "skipped")


def _normalize(row, index):
    if not isinstance(row, Mapping) or any(field not in row for field in _FIELDS):
        raise ValueError(f"Record {index}: a mapping with all six check-in fields is required")
    for field in ("id", "session_id"):
        if not isinstance(row[field], str) or not row[field].strip():
            raise ValueError(f"Record {index}: {field} must be a nonempty string")
    try:
        if not isinstance(row["answered_at"], str):
            raise ValueError("not a string")
        timestamp = datetime.fromisoformat(row["answered_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timezone missing")
        timestamp = timestamp.astimezone(UTC)
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"Record {index}: answered_at must be an aware ISO 8601 string") from exc
    state, value, clarity = row["stress_state"], row["stress_value"], row["clarity"]
    if not isinstance(state, str) or state not in ("answered", "unsure", "skipped", "expired"):
        raise ValueError(f"Record {index}: invalid stress_state")
    if state == "answered":
        if type(value) is not int or value not in (0, 1, 2):
            raise ValueError(f"Record {index}: answered stress_value must be integer 0, 1 or 2")
    elif value is not None:
        raise ValueError(f"Record {index}: unanswered stress_value must be null")
    if not isinstance(clarity, str) or clarity not in _CLARITY:
        raise ValueError(f"Record {index}: invalid clarity")
    return row["id"], (timestamp, row["session_id"], state, value, clarity)


def summarize_checkins(records):
    """Return daily UTC counts, total_checkins and days_with_checkins.

    Records are mappings with id, answered_at (aware ISO 8601 string),
    session_id, stress_state, stress_value and clarity. Extra fields are
    ignored. Zero entries yield an empty by_day list; one entry is counted
    without any trend conclusion. Only days containing records are returned.

    Duplicate IDs collapse when the six logical fields match after timestamp
    normalization to UTC; conflicting IDs or malformed input raise ValueError.
    No input mutation, I/O, averaging, imputation or clinical inference occurs.
    """
    if isinstance(records, (str, bytes, Mapping)):
        raise ValueError("Expected an iterable of check-in mappings")
    try:
        iterator = iter(records)
    except TypeError as exc:
        raise ValueError("Expected an iterable of check-in mappings") from exc

    seen, days = {}, {}
    for index, row in enumerate(iterator, 1):
        identifier, normalized = _normalize(row, index)
        if identifier in seen:
            if seen[identifier] != normalized:
                raise ValueError(f"Record {index}: conflicting duplicate check-in ID")
            continue
        seen[identifier] = normalized
        timestamp, _, state, value, clarity = normalized
        date = timestamp.date().isoformat()
        if date not in days:
            days[date] = {"date": date, "checkin_count": 0,
                          "stress_counts": dict.fromkeys(_STRESS, 0),
                          "clarity_counts": dict.fromkeys(_CLARITY, 0)}
        day = days[date]
        day["checkin_count"] += 1
        day["stress_counts"][_STRESS[value] if state == "answered" else state] += 1
        day["clarity_counts"][clarity] += 1
    return {"by_day": [days[date] for date in sorted(days)],
            "total_checkins": len(seen), "days_with_checkins": len(days)}
