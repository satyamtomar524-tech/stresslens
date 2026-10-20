"""Fictional row/CSV/range contracts; no device or personal input."""
import csv
import dataclasses
import importlib
import importlib.util
import io
from datetime import UTC, datetime, timedelta

import pytest


START = datetime(2026, 1, 1, 12, tzinfo=UTC)
FIELDS = ("timestamp", "metric", "value", "value_secondary", "unit", "device", "method", "source_id")


def api():
    assert importlib.util.find_spec("stresslens.session_measurements") is not None, "Pure measurement parser not implemented"
    return importlib.import_module("stresslens.session_measurements")


def row(**changes):
    return dict(timestamp=START.isoformat(), metric="heart_rate", value="70", value_secondary="",
                unit="bpm", device="fictional", method="synthetic", source_id="reading-1") | changes


def encoded(rows, fields=FIELDS):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def segment(identifier, start, seconds):
    from stresslens.session_report import SegmentAccumulator, SegmentConfig
    return SegmentAccumulator(SegmentConfig(), identifier, START + timedelta(seconds=start), start).finalize(seconds, "user_off")


def test_utf8_bom_reordered_columns_and_manual_rows_share_normalization():
    m = api()
    source = row(timestamp="2026-01-01T13:00:00+01:00", device="Fictional ❤️", source_id=" α-1 ")
    raw = b"\xef\xbb\xbf" + encoded([source], tuple(reversed(FIELDS)))
    parsed = m.parse_measurements_csv(raw, ingested_at=START + timedelta(seconds=10))
    manual = m.validate_measurement(source, ingested_at=START + timedelta(seconds=10))
    assert parsed == [manual]
    assert manual.timestamp == START and manual.value == 70
    assert manual.device == "Fictional ❤️" and manual.source_id == " α-1 "
    assert manual.ingested_at == START + timedelta(seconds=10)
    assert manual.segment_id is None


@pytest.mark.parametrize("changes", [
    {"timestamp": "2026-01-01T12:00:00"}, {"timestamp": "guess yesterday"},
    {"metric": "hrv_rmssd"}, {"unit": "beats/min"},
    {"value": "NaN"}, {"value": "inf"}, {"value": "-inf"},
    {"value": "0"}, {"value": "-1"}, {"value": "True"}, {"value": "=70+1"},
    {"value_secondary": "1"}, {"device": ""}, {"method": " "},
    {"source_id": ""}, {"device": "x" * 121}, {"method": "x" * 121},
    {"source_id": "x" * 121}, {"device": "bad\x00text"},
])
def test_bad_rows_fail_identically_for_csv_and_manual_validation(changes):
    m = api()
    for validate in [lambda: m.validate_measurement(row(**changes)),
                     lambda: m.parse_measurements_csv(encoded([row(**changes)]))]:
        with pytest.raises(ValueError):
            validate()


def test_manual_numeric_booleans_and_naive_ingestion_are_rejected():
    m = api()
    with pytest.raises(ValueError):
        m.validate_measurement(row(value=True))
    with pytest.raises(ValueError):
        m.validate_measurement(row(), ingested_at=datetime(2026, 1, 1))


@pytest.mark.parametrize("secondary", ["", "0", "120", "130", "nan", "-1"])
def test_blood_pressure_requires_structurally_valid_pair(secondary):
    m = api()
    with pytest.raises(ValueError):
        m.validate_measurement(row(metric="blood_pressure", unit="mmHg", value="120", value_secondary=secondary))


def test_sdnn_and_paired_bp_keep_units_without_deriving_stress():
    m = api()
    rows = m.parse_measurements_csv(encoded([
        row(metric="hrv_sdnn", unit="ms", value="40", source_id="hrv"),
        row(metric="blood_pressure", unit="mmHg", value="120", value_secondary="80", source_id="bp"),
    ]), ingested_at=START)
    assert [(x.metric, x.value, x.value_secondary, x.unit) for x in rows] == [
        ("hrv_sdnn", 40, None, "ms"), ("blood_pressure", 120, 80, "mmHg"),
    ]


@pytest.mark.parametrize("raw", [b"", b"timestamp,metric\n", b"\xff", b"x" * (1024 * 1024 + 1),
    b"timestamp,metric,value,value_secondary,unit,device,method,method\n",
    b"timestamp,metric,value,value_secondary,unit,device,method,source_id,extra\n"],
    ids=["empty", "short-header", "invalid-utf8", "over-one-mib", "duplicate-header", "extra-header"])
def test_encoding_byte_limit_and_exact_unique_columns(raw):
    m = api()
    with pytest.raises(ValueError):
        m.parse_measurements_csv(raw)


def test_malformed_width_quotes_and_multiple_errors_have_physical_row_numbers():
    m = api()
    raw = encoded([row(), row(source_id="bad-value", value="nan"), row(source_id="bad-unit", unit="unknown")])
    with pytest.raises(m.MeasurementValidationError) as caught:
        m.parse_measurements_csv(raw)
    assert "Row 3" in str(caught.value) and "Row 4" in str(caught.value)
    assert isinstance(caught.value.errors, tuple)
    for suffix in [b"only,two\n", b'"unclosed']:
        with pytest.raises(ValueError, match="Row 2"):
            m.parse_measurements_csv(encoded([]) + suffix)


def test_header_only_and_exact_one_mib_are_valid_without_hidden_trimming():
    m = api()
    assert m.parse_measurements_csv(encoded([])) == []
    raw = encoded([row()])
    raw += b"\n" * (1024 * 1024 - len(raw))
    assert len(m.parse_measurements_csv(raw, ingested_at=START)) == 1
    with pytest.raises(ValueError):
        m.parse_measurements_csv(raw + b"\n")


def test_ten_thousand_raw_rows_limit_precedes_deduplication():
    m = api()
    raw = encoded([row(source_id=str(i)) for i in range(10000)])
    assert len(raw) < 1024 * 1024
    assert len(m.parse_measurements_csv(raw, ingested_at=START)) == 10000
    with pytest.raises(ValueError, match="10000"):
        m.parse_measurements_csv(encoded([row()] * 10001))


def test_canonical_source_duplicates_collapse_but_true_conflicts_are_atomic():
    m = api()
    same = row(timestamp="2026-01-01T13:00:00+01:00", value="70.0")
    parsed = m.parse_measurements_csv(encoded([row(), same]), ingested_at=START)
    assert len(parsed) == 1
    for changed in [row(value="71"), row(device="different"), row(method="different"),
                    row(timestamp="2026-01-01T12:00:01Z")]:
        with pytest.raises(ValueError, match="conflict"):
            m.parse_measurements_csv(encoded([row(), row(source_id="new"), changed]))


def test_formula_html_and_urls_remain_literal_plain_text():
    m = api()
    record = m.validate_measurement(row(device="=1+1", method="<b>https://invalid.example</b>", source_id="@literal"))
    assert (record.device, record.method, record.source_id) == ("=1+1", "<b>https://invalid.example</b>", "@literal")


def test_preview_is_inclusive_in_range_and_half_open_in_camera_association():
    m = api()
    source = [m.validate_measurement(row(source_id=str(t), timestamp=(START + timedelta(seconds=t)).isoformat()), ingested_at=START)
              for t in [-1, 0, 10, 20, 30, 31]]
    before = tuple(source)
    preview = m.preview_measurements(source, START, START + timedelta(seconds=30),
                                     [segment("second", 20, 10), segment("first", 0, 10)])
    assert [r.source_id for r in preview.included] == ["0", "10", "20", "30"]
    assert [r.segment_id for r in preview.included] == ["first", None, "second", None]
    assert [r.source_id for r in preview.excluded] == ["-1", "31"]
    assert (preview.included_count, preview.excluded_count, preview.camera_on_count, preview.camera_off_count) == (4, 2, 2, 2)
    assert tuple(source) == before
    with pytest.raises(dataclasses.FrozenInstanceError):
        preview.included = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        preview.included[0].segment_id = "changed"


def test_preview_accepts_off_camera_context_and_requires_explicit_aware_range():
    m = api()
    reading = m.validate_measurement(row(), ingested_at=START)
    preview = m.preview_measurements([reading], START, START, [])
    assert preview.included_count == 1 and preview.camera_off_count == 1
    assert preview.included[0].segment_id is None
    for start, end in [(None, START), (START, None),
                       (START.replace(tzinfo=None), START), (START + timedelta(seconds=1), START)]:
        with pytest.raises(ValueError):
            m.preview_measurements([reading], start, end, [])


def test_preview_duplicates_ignore_ingestion_and_derived_association_keep_original():
    m = api()
    original = m.validate_measurement(row(), ingested_at=START)
    later = dataclasses.replace(original, ingested_at=START + timedelta(seconds=10), segment_id="stale")
    fresh = m.validate_measurement(row(source_id="new"), ingested_at=START)
    preview = m.preview_measurements([original, later, fresh], START, START, [])
    assert preview.duplicate_count == 1 and preview.included_count == 2
    assert preview.included[0].ingested_at == START
    assert preview.included[0].segment_id is None
    with pytest.raises(ValueError, match="conflict"):
        m.preview_measurements([original, fresh, dataclasses.replace(later, value=71)], START, START, [])


def test_preview_rejects_ambiguous_segments_and_preserves_inputs_on_error():
    m = api()
    readings = [m.validate_measurement(row(), ingested_at=START)]
    for segments in [[segment("a", 0, 20), segment("b", 10, 20)],
                     [segment("a", 0, 10), segment("a", 20, 10)], [{}]]:
        with pytest.raises(ValueError):
            m.preview_measurements(readings, START, START + timedelta(seconds=30), segments)
    assert readings[0].source_id == "reading-1" and readings[0].segment_id is None
