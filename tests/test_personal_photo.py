"""Session-only photo choices; synthetic pixels, no camera/SDK or disk saves."""
import importlib
import io
import random
from datetime import UTC, datetime

import pytest
from PIL import Image


def photo_api():
    return importlib.import_module("stresslens.personal_photo")


def picture(color="red", format="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(output, format=format)
    return output.getvalue()


def test_choice_survives_time_past_1700_without_expiry_or_renewal(monkeypatch):
    api = photo_api()
    state = {}
    before = datetime(2026, 10, 19, 14, 59, tzinfo=UTC)  # 16:59 Berlin
    monkeypatch.setattr(api, "utc_now", lambda: before)
    api.choose_photo(state, picture(), source="upload")
    chosen = api.get_photo(state)
    for after in (datetime(2026, 10, 19, 15, 1, tzinfo=UTC), datetime(2026, 11, 1, tzinfo=UTC)):
        monkeypatch.setattr(api, "utc_now", lambda: after)
        assert api.get_photo(state) is chosen
        assert chosen.selected_at == before
        assert Image.open(io.BytesIO(chosen.data)).getpixel((0, 0)) == (255, 0, 0)


@pytest.mark.parametrize("invalid", [b"broken image", b"", picture(format="GIF")])
def test_invalid_replacement_retains_previous_photo_and_associated_result(invalid):
    api = photo_api()
    state = {}
    api.choose_photo(state, picture(), source="upload")
    chosen = api.get_photo(state)
    state["analysis"] = {"fictional_marker": "previous correctly associated result"}
    with pytest.raises(ValueError):
        api.choose_photo(state, invalid, source="upload")
    assert api.get_photo(state) is chosen
    assert state["analysis"]["fictional_marker"] == "previous correctly associated result"


def test_oversized_replacement_does_not_destroy_previous_choice():
    api = photo_api()
    state = {}
    api.choose_photo(state, picture(), source="upload")
    chosen = api.get_photo(state)
    with pytest.raises(ValueError):
        api.choose_photo(state, b"x" * (40 * 1024 * 1024 + 1), source="upload")
    assert api.get_photo(state) is chosen


def test_normalized_image_size_limit_preserves_previous_choice(monkeypatch):
    api = photo_api()
    state = {}
    api.choose_photo(state, picture(), source="upload")
    chosen = api.get_photo(state)
    noise = Image.frombytes("RGB", (32, 32), random.Random(4).randbytes(32 * 32 * 3))
    compressed = io.BytesIO()
    noise.save(compressed, format="JPEG", quality=50)
    assert len(compressed.getvalue()) < 2000
    monkeypatch.setattr(api, "MAX_BYTES", 2000)
    with pytest.raises(ValueError):
        api.choose_photo(state, compressed.getvalue(), source="upload")
    assert api.get_photo(state) is chosen


def test_replacement_and_remove_invalidate_results_and_reject_delayed_completion():
    api = photo_api()
    retained_work, retained_history = object(), object()
    state = {"wellbeing_state": retained_work, "history_marker": retained_history}
    api.choose_photo(state, picture(), source="upload")
    old_revision = api.photo_revision(state)
    assert api.commit_analysis(state, {"example": False, "face": None}, expected_revision=old_revision)
    api.choose_photo(state, picture("blue"), source="upload")
    assert "analysis" not in state
    assert not api.commit_analysis(state, {"example": False, "old": True}, expected_revision=old_revision)
    assert "analysis" not in state
    current_revision = api.photo_revision(state)
    api.remove_photo(state)
    assert api.get_photo(state) is None
    assert not api.choose_photo(state, picture(), source="upload", expected_revision=current_revision)
    assert not api.commit_analysis(state, {"example": False}, expected_revision=current_revision)
    assert api.get_photo(state) is None and "analysis" not in state
    assert state["wellbeing_state"] is retained_work and state["history_marker"] is retained_history


def test_example_result_has_no_personal_photo_provenance_or_bytes():
    api = photo_api()
    state = {}
    api.choose_photo(state, picture(), source="upload")
    chosen = api.get_photo(state)
    api.commit_analysis(state, {"example": True, "face": None}, expected_revision=api.photo_revision(state))
    assert api.get_photo(state) is chosen
    assert state["analysis"].get("photo") is None
    assert state["analysis"].get("photo_revision") is None


def test_personal_analysis_binds_only_safe_selection_metadata():
    api = photo_api()
    state = {}
    api.choose_photo(state, picture(), source="upload")
    assert api.commit_analysis(state, {"example": False, "media_source": "selected_photo"},
                               expected_revision=api.photo_revision(state))
    metadata = state["analysis"]["photo"]
    assert set(metadata) == {"source", "selected_at_utc"}
    assert metadata["source"] == "upload"
    assert metadata["selected_at_utc"].endswith("+00:00")
    assert all(not isinstance(value, bytes) for value in metadata.values())
