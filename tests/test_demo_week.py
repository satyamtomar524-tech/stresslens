"""Hand-counted fictional examples; no personal or camera data."""
from collections import Counter
from datetime import UTC, datetime
import json

import pytest

from stresslens.personal_patterns import summarize_checkins


def demo_week():
    try:
        from stresslens.demo_week import get_demo_week
    except ModuleNotFoundError as exc:
        if exc.name != "stresslens.demo_week":
            raise
        pytest.fail("The agreed get_demo_week API has not been implemented")
    return get_demo_week()


def test_fictional_contract_is_explicit_and_json_compatible():
    week = demo_week()
    assert {key: value for key, value in week.items() if key != "records"} == {
        "schema": "fictional-week/1", "is_fictional": True,
        "title": "Fictional week — example only",
        "start_date": "2026-10-05", "end_date": "2026-10-11",
    }
    assert json.loads(json.dumps(week, allow_nan=False)) == week


def test_fourteen_unique_points_cover_each_utc_day_twice():
    rows = demo_week()["records"]
    assert len(rows) == len({row["id"] for row in rows}) == 14
    assert all(row["id"].startswith("demo-week-") for row in rows)
    assert all(row["session_id"].startswith("demo-week-") for row in rows)
    timestamps = [datetime.fromisoformat(row["answered_at"]) for row in rows]
    assert all(stamp.tzinfo is not None and stamp.utcoffset().total_seconds() == 0
               for stamp in timestamps)
    assert timestamps == sorted(timestamps)
    assert Counter(stamp.astimezone(UTC).date().isoformat() for stamp in timestamps) == {
        "2026-10-05": 2, "2026-10-06": 2, "2026-10-07": 2,
        "2026-10-08": 2, "2026-10-09": 2, "2026-10-10": 2, "2026-10-11": 2,
    }


def test_points_use_only_the_accepted_six_fields_and_category_values():
    rows = demo_week()["records"]
    fields = {"id", "answered_at", "session_id", "stress_state", "stress_value", "clarity"}
    for row in rows:
        assert set(row) == fields
        assert row["stress_state"] in {"answered", "unsure", "skipped"}
        if row["stress_state"] == "answered":
            assert type(row["stress_value"]) is int and row["stress_value"] in (0, 1, 2)
        else:
            assert row["stress_value"] is None
        assert row["clarity"] in {"clear", "mixed", "foggy", "unsure", "skipped"}


def test_summary_matches_hand_counted_daily_values():
    # Counts are independently specified in category order, including zeroes.
    expected_days = [
        ("2026-10-05", (1, 1, 0, 0, 0, 0), (1, 1, 0, 0, 0)),
        ("2026-10-06", (0, 0, 1, 1, 0, 0), (0, 0, 1, 1, 0)),
        ("2026-10-07", (1, 0, 0, 0, 1, 0), (0, 1, 0, 0, 1)),
        ("2026-10-08", (0, 1, 1, 0, 0, 0), (1, 0, 1, 0, 0)),
        ("2026-10-09", (0, 1, 0, 1, 0, 0), (0, 0, 0, 1, 1)),
        ("2026-10-10", (0, 0, 1, 0, 1, 0), (1, 1, 0, 0, 0)),
        ("2026-10-11", (1, 0, 1, 0, 0, 0), (0, 0, 1, 1, 0)),
    ]
    expected = {
        "by_day": [{
            "date": date, "checkin_count": 2,
            "stress_counts": dict(zip(
                ("none", "low", "high", "unsure", "skipped", "expired"), stress, strict=True)),
            "clarity_counts": dict(zip(
                ("clear", "mixed", "foggy", "unsure", "skipped"), clarity, strict=True)),
        } for date, stress, clarity in expected_days],
        "total_checkins": 14, "days_with_checkins": 7,
    }
    assert summarize_checkins(demo_week()["records"]) == expected


def test_missing_responses_stay_separate_from_zero_answers():
    summary = summarize_checkins(demo_week()["records"])
    stress = Counter()
    clarity = Counter()
    for day in summary["by_day"]:
        stress.update(day["stress_counts"])
        clarity.update(day["clarity_counts"])
    assert dict(stress) == {
        "none": 3, "low": 3, "high": 4, "unsure": 2, "skipped": 2, "expired": 0,
    }
    assert dict(clarity) == {"clear": 3, "mixed": 3, "foggy": 3, "unsure": 3, "skipped": 2}


def test_every_call_returns_isolated_nested_data():
    first, second = demo_week(), demo_week()
    baseline = json.loads(json.dumps(second))
    assert first == second
    assert first is not second and first["records"] is not second["records"]
    assert first["records"][0] is not second["records"][0]
    first["title"] = "changed locally"
    first["records"][0]["clarity"] = "changed locally"
    first["records"].append({"not": "a check-in"})
    assert second == baseline
    second["records"].clear()
    assert demo_week() == baseline
