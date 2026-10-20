"""Explicitly invoked, bounded local check-in history; no camera or timer state."""
from collections.abc import Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from stresslens.wellbeing import CLARITY_VALUES


SCHEMA = "stresslens-checkin-history/1"
MAX_RECORDS = 10000
MAX_BYTES = 4 * 1024 * 1024


class HistoryError(ValueError):
    pass


def default_history_path():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "StressLens" / "checkin-history-v1.json"


def _identifier(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 120:
        raise HistoryError("History requires bounded, nonempty record and session IDs.")
    value.encode("utf-8")
    return value


def _record(row):
    if not isinstance(row, Mapping):
        raise HistoryError("History contains an invalid check-in record.")
    try:
        stamp = row["answered_at"]
        if not isinstance(stamp, str) or len(stamp) > 64:
            raise ValueError
        when = datetime.fromisoformat(stamp)
        if when.tzinfo is None or when.utcoffset() is None:
            raise ValueError
        state, value, clarity = row["stress_state"], row["stress_value"], row["clarity"]
        if state not in {"answered", "unsure", "skipped", "expired"} or clarity not in CLARITY_VALUES:
            raise ValueError
        if state == "answered":
            if type(value) is not int or value not in {0, 1, 2}:
                raise ValueError
        elif value is not None:
            raise ValueError
        return {"id": _identifier(row["id"]), "answered_at": when.astimezone(UTC).isoformat(),
                "session_id": _identifier(row["session_id"]), "stress_state": state,
                "stress_value": value, "clarity": clarity}
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HistoryError("History contains an invalid timestamp, answer or identifier; no file was changed.") from exc


def merge_checkins(existing, incoming):
    unique = {}
    for batch in (existing, incoming):
        if not isinstance(batch, (list, tuple)) or len(batch) > MAX_RECORDS:
            raise HistoryError(f"History is limited to {MAX_RECORDS:,} check-ins; nothing was evicted.")
        for row in batch:
            clean = _record(row)
            prior = unique.get(clean["id"])
            if prior is not None and prior != clean:
                raise HistoryError("Conflicting check-in IDs; existing history was not changed.")
            unique[clean["id"]] = clean
            if len(unique) > MAX_RECORDS:
                raise HistoryError(f"History is limited to {MAX_RECORDS:,} check-ins; nothing was evicted.")
    return sorted(unique.values(), key=lambda row: (row["answered_at"], row["id"]))


def load_history(path):
    path = Path(path)
    try:
        with path.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise HistoryError("Local history could not be read; no file was changed.") from exc
    if len(raw) > MAX_BYTES:
        raise HistoryError("Local history exceeds the 4 MiB limit; no file was changed.")
    try:
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
            raise ValueError
        return merge_checkins([], payload["records"])
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise HistoryError("Local history is malformed or unsupported; it was not overwritten.") from exc


@contextmanager
def _save_lock(path):
    lock = path.with_suffix(".lock")
    token = uuid4().hex
    try:
        handle = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HistoryError("Local history is busy or an earlier save lock remains; no history was changed.") from exc
    try:
        with os.fdopen(handle, "w", encoding="ascii") as stream:
            stream.write(token)
        yield
    finally:
        try:
            if lock.read_text(encoding="ascii") == token:
                lock.unlink()
        except OSError:
            pass


def save_history(path, records):
    path, temporary = Path(path), None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with _save_lock(path):
            combined = merge_checkins(load_history(path), records)
            encoded = json.dumps({"schema": SCHEMA, "records": combined}, ensure_ascii=False,
                                 allow_nan=False, indent=2).encode("utf-8")
            if len(encoded) > MAX_BYTES:
                raise HistoryError("Local history exceeds the 4 MiB limit; nothing was overwritten.")
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix="checkins-", suffix=".tmp", delete=False) as target:
                temporary = Path(target.name)
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, path)
            temporary = None
            return combined
    except OSError as exc:
        raise HistoryError("Local history could not be saved; existing history was retained.") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
