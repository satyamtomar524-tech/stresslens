"""Opt-in store functions operate only on disposable temporary directories."""
import json

import pytest

from stresslens.wellbeing_store import HistoryError, load_history, merge_checkins, save_history


def point(identifier="fictional-1", **changes):
    return {"id": identifier, "answered_at": "2026-10-18T09:00:00Z", "session_id": "fictional-work",
            "stress_state": "answered", "stress_value": 0, "clarity": "clear", **changes}


def test_missing_history_load_has_no_filesystem_side_effect(tmp_path):
    path = tmp_path / "absent" / "history.json"
    assert load_history(path) == [] and not path.parent.exists()


def test_versioned_store_is_bounded_categorical_atomic_and_idempotent(tmp_path):
    path = tmp_path / "private" / "history.json"
    saved = save_history(path, [point(free_text="Fictional field to omit", camera="omit")])
    assert saved[0]["answered_at"] == "2026-10-18T09:00:00+00:00"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema"] == "stresslens-checkin-history/1"
    assert set(raw["records"][0]) == {"id", "answered_at", "session_id", "stress_state", "stress_value", "clarity"}
    assert load_history(path) == saved
    assert save_history(path, [point(answered_at="2026-10-18T11:00:00+02:00")]) == saved
    assert not list(path.parent.glob("*.tmp")) and not path.with_suffix(".lock").exists()


def test_conflicting_id_leaves_existing_history_unchanged(tmp_path):
    path = tmp_path / "history.json"
    save_history(path, [point()])
    before = path.read_bytes()
    with pytest.raises(HistoryError):
        save_history(path, [point(stress_value=2)])
    assert path.read_bytes() == before


@pytest.mark.parametrize("payload", [b"not-json", b'{"schema":"unknown","records":[]}',
                                     b'{"schema":"stresslens-checkin-history/1","records":[{}]}'])
def test_malformed_history_is_never_overwritten(tmp_path, payload):
    path = tmp_path / "history.json"
    path.write_bytes(payload)
    with pytest.raises(HistoryError):
        load_history(path)
    with pytest.raises(HistoryError):
        save_history(path, [point()])
    assert path.read_bytes() == payload
    assert not path.with_suffix(".lock").exists()


def test_failed_atomic_replace_keeps_original_and_removes_only_owned_temp(tmp_path, monkeypatch):
    import stresslens.wellbeing_store as store
    path = tmp_path / "history.json"
    save_history(path, [point()])
    before = path.read_bytes()
    def fail_replace(*args):
        raise OSError("Synthetic disk failure")
    monkeypatch.setattr(store.os, "replace", fail_replace)
    with pytest.raises(HistoryError):
        save_history(path, [point("fictional-2")])
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp")) and not path.with_suffix(".lock").exists()


def test_busy_store_does_not_remove_someone_elses_lock_or_overwrite(tmp_path):
    path = tmp_path / "history.json"
    save_history(path, [point()])
    before = path.read_bytes()
    lock = path.with_suffix(".lock")
    lock.write_text("fictional concurrent writer", encoding="utf-8")
    with pytest.raises(HistoryError):
        save_history(path, [point("fictional-2")])
    assert path.read_bytes() == before and lock.read_text(encoding="utf-8") == "fictional concurrent writer"


def test_history_cap_is_visible_and_does_not_evict_old_records(tmp_path, monkeypatch):
    import stresslens.wellbeing_store as store
    monkeypatch.setattr(store, "MAX_RECORDS", 2)
    path = tmp_path / "history.json"
    save_history(path, [point("one"), point("two")])
    before = path.read_bytes()
    with pytest.raises(HistoryError):
        save_history(path, [point("three")])
    assert path.read_bytes() == before


@pytest.mark.parametrize("changes", [
    {"answered_at": "2026-10-18T09:00:00"}, {"stress_value": True},
    {"stress_state": "unsure", "stress_value": 0}, {"stress_value": 3},
    {"clarity": "productive"}, {"session_id": None}, {"id": ""},
    {"id": "\ud800"},
])
def test_invalid_records_are_rejected_before_commit(changes):
    with pytest.raises(HistoryError):
        merge_checkins([], [point(**changes)])


def test_oversized_history_is_rejected_without_overwrite(tmp_path, monkeypatch):
    import stresslens.wellbeing_store as store
    monkeypatch.setattr(store, "MAX_BYTES", 100)
    path = tmp_path / "history.json"
    raw = b" " * 101
    path.write_bytes(raw)
    with pytest.raises(HistoryError):
        load_history(path)
    with pytest.raises(HistoryError):
        save_history(path, [point()])
    assert path.read_bytes() == raw


def test_encoded_history_limit_rejects_before_first_commit(tmp_path, monkeypatch):
    import stresslens.wellbeing_store as store
    monkeypatch.setattr(store, "MAX_BYTES", 100)
    path = tmp_path / "history.json"
    with pytest.raises(HistoryError):
        save_history(path, [point()])
    assert not path.exists() and not path.with_suffix(".lock").exists()
    assert not list(tmp_path.glob("*.tmp"))
