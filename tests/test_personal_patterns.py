"""Fictional point check-ins; counts must not invent stress trends."""
from copy import deepcopy
import json

import pytest


def summarize(records):
    try:
        from stresslens.personal_patterns import summarize_checkins
    except ModuleNotFoundError:
        pytest.fail("The agreed summarize_checkins API has not been implemented")
    return summarize_checkins(records)


def record(**changes):
    return {"id": "fictional-1", "answered_at": "2026-10-18T12:00:00Z",
            "session_id": "fictional-session", "stress_state": "answered",
            "stress_value": 0, "clarity": "clear", **changes}


def test_empty_history_has_no_days_or_invented_insufficient_data_flag():
    assert summarize([]) == {"by_day": [], "total_checkins": 0, "days_with_checkins": 0}


def test_single_zero_answer_is_counted_as_none_not_missing():
    assert summarize([record()]) == {
        "by_day": [{"date": "2026-10-18", "checkin_count": 1,
                    "stress_counts": {"none": 1, "low": 0, "high": 0, "unsure": 0, "skipped": 0, "expired": 0},
                    "clarity_counts": {"clear": 1, "mixed": 0, "foggy": 0, "unsure": 0, "skipped": 0}}],
        "total_checkins": 1, "days_with_checkins": 1,
    }


def test_offset_normalization_sorts_utc_days_and_does_not_fill_missing_days():
    rows = [record(id="a", answered_at="2026-10-19T00:15:00+02:00", stress_value=2, clarity="foggy"),
            record(id="b", answered_at="2026-10-17T23:30:00-02:00", stress_state="unsure", stress_value=None),
            record(id="c", answered_at="2026-10-16T12:00:00+00:00", stress_value=1, clarity="mixed")]
    result = summarize(rows)
    assert result == summarize(reversed(rows))
    assert [day["date"] for day in result["by_day"]] == ["2026-10-16", "2026-10-18"]
    assert [day["checkin_count"] for day in result["by_day"]] == [1, 2]
    assert result["total_checkins"] == 3 and result["days_with_checkins"] == 2
    assert result["by_day"][0]["stress_counts"]["low"] == 1
    assert result["by_day"][1]["stress_counts"] == {
        "none": 0, "low": 0, "high": 1, "unsure": 1, "skipped": 0, "expired": 0}
    assert result["by_day"][1]["clarity_counts"] == {
        "clear": 1, "mixed": 0, "foggy": 1, "unsure": 0, "skipped": 0}


def test_all_missing_states_and_clarity_categories_remain_separate_counts():
    rows = [record(id="a"), record(id="b", stress_value=1, clarity="mixed"),
            record(id="c", stress_value=2, clarity="foggy"),
            record(id="d", stress_state="unsure", stress_value=None, clarity="unsure"),
            record(id="e", stress_state="skipped", stress_value=None, clarity="skipped"),
            record(id="f", stress_state="expired", stress_value=None, clarity="skipped")]
    day = summarize(rows)["by_day"][0]
    assert day["checkin_count"] == 6
    assert day["stress_counts"] == {"none": 1, "low": 1, "high": 1, "unsure": 1, "skipped": 1, "expired": 1}
    assert day["clarity_counts"] == {"clear": 1, "mixed": 1, "foggy": 1, "unsure": 1, "skipped": 2}


def test_identical_ids_dedup_with_utc_equivalence_and_ignored_extra_fields():
    first = record(answered_at="2026-10-18T14:00:00+02:00", extra="ignored")
    duplicate = record(answered_at="2026-10-18T12:00:00Z", extra={"different": True})
    assert summarize([first, duplicate]) == summarize([first])
    assert summarize([first, record(id="different-id")])["total_checkins"] == 2


@pytest.mark.parametrize("change", [
    {"answered_at": "2026-10-18T12:00:01Z"}, {"session_id": "different-session"},
    {"stress_value": 1}, {"stress_state": "unsure", "stress_value": None}, {"clarity": "mixed"},
])
def test_conflicting_duplicate_id_rejects_without_mutating_input(change):
    rows = [record(), record(**change)]
    before = deepcopy(rows)
    with pytest.raises(ValueError):
        summarize(rows)
    assert rows == before


@pytest.mark.parametrize("field", ["id", "answered_at", "session_id", "stress_state", "stress_value", "clarity"])
def test_missing_required_fields_are_not_defaulted(field):
    row = record()
    del row[field]
    with pytest.raises(ValueError):
        summarize([row])


@pytest.mark.parametrize("change", [
    {"id": ""}, {"id": "  "}, {"id": 1}, {"session_id": ""}, {"session_id": None},
    {"answered_at": None}, {"answered_at": "not-a-time"}, {"answered_at": "2026-10-18"},
    {"answered_at": "2026-10-18T12:00:00"}, {"answered_at": "0001-01-01T00:00:00+14:00"},
    {"stress_state": "high"}, {"stress_state": None}, {"stress_value": None},
    {"stress_value": True}, {"stress_value": 1.0}, {"stress_value": "0"},
    {"stress_value": -1}, {"stress_value": 3}, {"clarity": None}, {"clarity": "focused"},
    {"clarity": []}, {"stress_state": []},
])
def test_malformed_fields_are_rejected_instead_of_guessed(change):
    with pytest.raises(ValueError):
        summarize([record(**change)])


@pytest.mark.parametrize("state", ["unsure", "skipped", "expired"])
def test_unanswered_states_must_have_null_stress_value(state):
    with pytest.raises(ValueError):
        summarize([record(stress_state=state, stress_value=0)])


@pytest.mark.parametrize("rows", [None, 1, True, "records", {"id": "not-a-record-list"}, [None], [1]])
def test_invalid_containers_or_non_mapping_rows_raise_value_error(rows):
    with pytest.raises(ValueError):
        summarize(rows)


def test_input_and_output_are_detached_and_only_descriptive_counts_are_returned():
    rows = [record(extra={"nested": [1, 2]})]
    before = deepcopy(rows)
    result = summarize(iter(rows))
    assert rows == before
    assert set(result) == {"by_day", "total_checkins", "days_with_checkins"}
    assert set(result["by_day"][0]) == {"date", "checkin_count", "stress_counts", "clarity_counts"}
    assert json.loads(json.dumps(result, allow_nan=False)) == result
    result["by_day"][0]["clarity_counts"]["clear"] = 999
    assert summarize(rows)["by_day"][0]["clarity_counts"]["clear"] == 1
