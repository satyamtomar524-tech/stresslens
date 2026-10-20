"""Pure normalized measurement parsing and read-only preview.

No file/device/account access, formula evaluation, clock correction or commit.
The caller enables preview/import only while capture is off. The workspace
commit API owns cumulative retention limits and cross-import deduplication;
a successful preview does not promise that a subsequent commit will fit.
"""
from __future__ import annotations

import csv
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from stresslens.session_report import Measurement, SegmentReport


COLUMNS = ("timestamp", "metric", "value", "value_secondary", "unit", "device", "method", "source_id")
MAX_BYTES = 1024 * 1024
MAX_ROWS = 10000
UNITS = {"heart_rate": "bpm", "hrv_sdnn": "ms", "blood_pressure": "mmHg"}


class MeasurementValidationError(ValueError):
    def __init__(self, errors):
        self.errors = (errors,) if isinstance(errors, str) else tuple(errors)
        super().__init__("\n".join(self.errors))


def _fail(field, message, row_number):
    raise MeasurementValidationError(f"Row {row_number}: {field}: {message}")


def _aware(value, field, row_number):
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value)
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("missing timezone")
        return value.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        _fail(field, "explicit-offset ISO 8601 time or aware datetime required", row_number)


def _positive(value, field, row_number):
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError("not numeric")
        value = float(value)
        if not math.isfinite(value) or value <= 0:
            raise ValueError("not finite and positive")
        return value
    except (TypeError, ValueError, OverflowError):
        _fail(field, "finite positive number required", row_number)


def _plain_text(value, field, row_number):
    if not isinstance(value, str) or not value.strip() or len(value) > 120 or "\x00" in value:
        _fail(field, "required plain text, at most 120 characters", row_number)
    return value  # Preserve identifiers/provenance literally; never evaluate markup.


def _source_key(row):
    """Source reading identity, deliberately excluding ingestion/association."""
    return (row.source_id, row.timestamp, row.metric, row.value, row.value_secondary,
            row.unit, row.device, row.method)


def validate_measurement(row, *, ingested_at=None, row_number=1):
    """Validate the same eight source fields for manual and CSV inputs.

    Optional ingestion time is application metadata, never an imported column.
    Numeric normalization does not convert units or infer clinical validity.
    """
    if not isinstance(row, Mapping) or set(row) != set(COLUMNS):
        _fail("columns", "exact eight source columns required", row_number)
    timestamp = _aware(row["timestamp"], "timestamp", row_number)
    metric, unit = row["metric"], row["unit"]
    if not isinstance(metric, str) or metric not in UNITS:
        _fail("metric", "unsupported metric", row_number)
    if unit != UNITS[metric]:
        _fail("unit", "unsupported metric/unit pair; no conversion performed", row_number)
    value = _positive(row["value"], "value", row_number)
    secondary = row["value_secondary"]
    if metric == "blood_pressure":
        secondary = _positive(secondary, "value_secondary", row_number)
        if secondary >= value:
            _fail("value_secondary", "paired diastolic value must be below systolic", row_number)
    elif secondary is None or secondary == "":
        secondary = None
    else:
        _fail("value_secondary", "must be empty except for blood pressure", row_number)
    device = _plain_text(row["device"], "device", row_number)
    method = _plain_text(row["method"], "method", row_number)
    source_id = _plain_text(row["source_id"], "source_id", row_number)
    ingestion = _aware(datetime.now(UTC) if ingested_at is None else ingested_at,
                       "ingested_at", row_number)
    return Measurement(source_id, timestamp, metric, value, unit, device, method,
                       ingestion, value_secondary=secondary)


def parse_measurements_csv(raw: bytes, *, ingested_at=None) -> list[Measurement]:
    """Atomically parse at most 1 MiB / 10000 raw data records.

    Accept a leading UTF-8 BOM and arbitrary order of the eight exact unique
    headers. Ignore empty physical records; quoted newlines remain CSV text.
    Duplicate source readings preserve the first ingestion record. Any error
    rejects the whole batch with physical source-row numbers.
    """
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES:
        _fail("file", "UTF-8 bytes required, maximum 1 MiB", 1)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        _fail("encoding", "valid UTF-8 required", 1)
    reader = csv.reader(io.StringIO(decoded, newline=""), strict=True)
    try:
        headers = next(reader, None)
    except csv.Error:
        _fail("header", "malformed CSV", 1)
    if headers is None or len(headers) != len(COLUMNS) or set(headers) != set(COLUMNS):
        _fail("header", "exact eight unique source columns required", 1)
    ingestion = _aware(datetime.now(UTC) if ingested_at is None else ingested_at, "ingested_at", 1)
    records, errors, seen = [], [], {}
    raw_count = 0
    while True:
        line = reader.line_num + 1
        try:
            values = next(reader)
        except StopIteration:
            break
        except csv.Error:
            errors.append(f"Row {line}: malformed CSV")
            break
        if not values:
            continue
        raw_count += 1
        if raw_count > MAX_ROWS:
            errors.append(f"Row {line}: maximum 10000 data rows exceeded before deduplication")
            break
        if len(values) != len(COLUMNS):
            errors.append(f"Row {line}: expected exactly eight values")
            continue
        try:
            record = validate_measurement(dict(zip(headers, values, strict=True)),
                                          ingested_at=ingestion, row_number=line)
        except MeasurementValidationError as exc:
            errors.extend(exc.errors)
            continue
        previous = seen.get(record.source_id)
        if previous is not None:
            if _source_key(previous) != _source_key(record):
                errors.append(f"Row {line}: conflicting source_id reading")
        else:
            seen[record.source_id] = record
            records.append(record)
    if errors:
        raise MeasurementValidationError(errors)
    return records


@dataclass(frozen=True)
class ImportPreview:
    range_start_utc: datetime
    range_end_utc: datetime
    included: tuple[Measurement, ...]
    excluded: tuple[Measurement, ...]
    duplicate_count: int
    alignment_notice: str = "Device clocks may differ; timestamps were not shifted."

    @property
    def included_count(self):
        return len(self.included)

    @property
    def excluded_count(self):
        return len(self.excluded)

    @property
    def camera_on_count(self):
        return sum(row.segment_id is not None for row in self.included)

    @property
    def camera_off_count(self):
        return self.included_count - self.camera_on_count


def _segments(segments):
    intervals = []
    identifiers = set()
    for segment in segments:
        if not isinstance(segment, SegmentReport):
            _fail("segments", "finalized SegmentReport values required", 1)
        start = _aware(segment.start_utc, "segment start", 1)
        end = _aware(segment.end_utc, "segment end", 1)
        if end < start or not isinstance(segment.segment_id, str) or not segment.segment_id.strip():
            _fail("segments", "invalid segment interval or ID", 1)
        if segment.segment_id in identifiers:
            _fail("segments", "duplicate segment ID", 1)
        identifiers.add(segment.segment_id)
        intervals.append((start, end, segment.segment_id))
    intervals.sort()
    previous_end = None
    for start, end, _ in intervals:
        if start == end:
            continue  # Empty half-open segments own no measurement instant.
        if previous_end is not None and start < previous_end:
            _fail("segments", "overlapping intervals make association ambiguous", 1)
        previous_end = end
    return intervals


def preview_measurements(rows, range_start_utc, range_end_utc, segments) -> ImportPreview:
    """Read-only range preview; no automatic expansion, clock shift or commit.

    Range endpoints are inclusive. Camera association is independently
    half-open [start,end). Rows outside camera segments are valid context.
    Cumulative workspace capacity is checked only by its separate commit API.
    """
    start = _aware(range_start_utc, "range start", 1)
    end = _aware(range_end_utc, "range end", 1)
    if start > end:
        _fail("range", "start must not exceed end", 1)
    intervals = _segments(segments)
    included, excluded, errors, seen = [], [], [], {}
    duplicates = 0
    for index, row in enumerate(rows, 1):
        if index > MAX_ROWS:
            errors.append(f"Row {index}: maximum 10000 preview input rows exceeded")
            break
        if not isinstance(row, Measurement):
            errors.append(f"Row {index}: validated Measurement required")
            continue
        previous = seen.get(row.source_id)
        if previous is not None:
            if _source_key(previous) == _source_key(row):
                duplicates += 1
            else:
                errors.append(f"Row {index}: conflicting source_id reading")
            continue
        seen[row.source_id] = row
        association = next((identifier for a, b, identifier in intervals if a <= row.timestamp < b), None)
        normalized = replace(row, segment_id=association)
        (included if start <= row.timestamp <= end else excluded).append(normalized)
    if errors:
        raise MeasurementValidationError(errors)
    return ImportPreview(start, end, tuple(included), tuple(excluded), duplicates)
