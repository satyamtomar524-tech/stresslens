import copy
import math

import pytest

from stresslens.insights import research_insights


def test_numeric_changes_are_ranked_and_reference_inputs_preserved():
    snapshot = {
        "status": "ok",
        "groups": {"Brow lowering": 0.5, "Eye narrowing": 0.1, "Smile shape": 0.5},
        "baseline": {"Brow lowering": 0.1, "Eye narrowing": 0.6, "Smile shape": 0.2},
        "changes": {"Brow lowering": -0.8},  # Deliberately inconsistent stale delta.
        "history": [{"seconds": 1, "Eye narrowing": 0.2}],
    }
    original = copy.deepcopy(snapshot)
    cards = research_insights(snapshot)
    assert len(cards) == 2
    assert "Eye narrowing coefficient decreased" == cards[0]["title"]
    assert "-0.50 (lower)" in cards[0]["observation"]
    assert "0.10 now versus 0.60" in cards[0]["observation"]
    assert "+0.40 (higher)" in cards[1]["observation"]
    assert cards[1]["source_id"] == "giannakakis-2025"
    assert "engineering display threshold" in cards[0]["limitation"]
    assert snapshot == original


@pytest.mark.parametrize("status", ["waiting", "no_face", "multiple_faces", "stale", "error", "too_far", "stopped"])
def test_unavailable_faces_never_receive_research_cards(status):
    assert research_insights({"status": status, "groups": {"Brow lowering": 0.9}}) == []


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, True, "0.8", None, -0.1, 1.1])
def test_nonfinite_or_invalid_coefficients_do_not_become_observations(value):
    assert research_insights({"status": "ok", "groups": {"Brow lowering": value}}) == []
    assert research_insights({"status": "ok", "groups": {"Brow lowering": 0.8},
                              "baseline": {"Brow lowering": value}}) == []


@pytest.mark.parametrize("snapshot", [None, {}, {"status": "ok"}, {"status": "ok", "groups": {}},
                                    {"status": "ok", "groups": {"Unknown feature": 0.8}}])
def test_missing_or_unknown_measurements_produce_no_inference(snapshot):
    assert research_insights(snapshot) == []


def test_current_shape_without_reference_does_not_imply_increase_or_feelings():
    cards = research_insights({"status": "ok", "groups": {"Lip pressing": 0.7, "Smile shape": 0.3}})
    assert "0.70 now" in cards[0]["observation"]
    assert "cannot be inferred" in cards[0]["observation"]
    assert cards[0]["source_id"] == "empathicschool-2025"
    assert "does not establish how someone feels" in cards[1]["research_connection"]


def test_near_reference_is_not_labeled_low_stress():
    cards = research_insights({"status": "ok", "groups": {"Brow lowering": 0.21},
                              "baseline": {"Brow lowering": 0.2}})
    assert len(cards) == 1
    assert "+0.01" in cards[0]["observation"]
    assert "not low stress or calmness" in cards[0]["observation"]
    assert "not a stress threshold" in cards[0]["limitation"]


def test_threshold_boundary_is_a_display_change_and_has_no_scores():
    cards = research_insights({"status": "ok", "groups": {"Brow lowering": 0.25},
                              "baseline": {"Brow lowering": 0.1}})
    assert "increased" in cards[0]["title"]
    required = {"title", "observation", "research_connection", "alternatives", "limitation",
                "source_title", "source_url", "source_id"}
    assert set(cards[0]) == required
    assert "%" not in cards[0]["observation"]


@pytest.mark.parametrize("age", [2.1, -1, math.nan, math.inf, "fresh", True])
def test_stale_or_invalid_frame_age_is_rejected_even_if_status_says_ok(age):
    assert research_insights({"status": "ok", "frame_age_seconds": age,
                              "groups": {"Brow lowering": 0.8}}) == []


def test_incomplete_reference_capture_produces_no_cards():
    assert research_insights({"status": "ok", "groups": {"Brow lowering": 0.8},
                              "reference_progress": 0.5}) == []


def test_source_titles_urls_and_ids_match_and_alternatives_are_copies():
    expected = {
        "blasberg-2023": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10422124/",
        "giannakakis-2025": "https://pubmed.ncbi.nlm.nih.gov/39608217/",
        "empathicschool-2025": "https://www.nature.com/articles/s41597-025-05812-0",
    }
    for name in ("Brow lowering", "Eye narrowing", "Lip pressing", "Smile shape", "Eye closure", "Jaw opening"):
        snapshot = {"status": "ok", "groups": {name: 0.8}}
        card = research_insights(snapshot)[0]
        assert card["source_url"] == expected[card["source_id"]]
        assert card["source_title"]
        assert "not validated here" in card["limitation"]
        card["alternatives"].append("mutation")
        assert "mutation" not in research_insights(snapshot)[0]["alternatives"]


def test_eye_closure_history_is_not_reported_as_blink_rate():
    snapshot = {"status": "ok", "groups": {"Eye closure": 0.8},
                "history": [{"seconds": 0, "Eye closure": 0.0}, {"seconds": 1, "Eye closure": 0.8}]}
    card = research_insights(snapshot)[0]
    assert "blink-rate measurement" in card["research_connection"]
    assert "blinks per" not in card["observation"]
