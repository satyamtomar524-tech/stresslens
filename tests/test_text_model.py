"""Integration tests use the actual locally trained model, without network access."""

from pathlib import Path

import pytest

from stresslens.text_model import analyze_text


def test_actual_bundled_model_inference_is_repeatable():
    text = "I feel overwhelmed by work and cannot sleep because I keep worrying about everything I need to finish."
    first = analyze_text(text)
    assert first["status"] == "ok"
    assert 0 <= first["stress_probability"] <= 1
    assert first == analyze_text(text)
    assert first["top_terms"]
    assert all(item["term"] in text.lower() for item in first["top_terms"])
    assert any("uncalibrated" in warning for warning in first["warnings"])
    assert "diagnose" in " ".join(first["warnings"])


@pytest.mark.parametrize("text", ["", "   ", "I am stressed", "123 456 789", "stress " * 10, "a " * 2001, None])
def test_insufficient_input_abstains(text):
    result = analyze_text(text)
    assert result["status"] == "insufficient"
    assert result["stress_probability"] is None
    assert result["top_terms"] == []


@pytest.mark.parametrize("text", [
    "xyzzq qqqq zzzz plmnk jjjj kkkk wwww gggg pppp",
    "我今天觉得很累，工作压力非常大，晚上也总是睡不好觉。",
    "Ich fühle mich heute sehr überfordert und kann nachts wegen meiner Arbeit nicht schlafen.",
    "Estoy muy preocupado por mi trabajo y no puedo dormir durante la noche.",
])
def test_unsupported_language_or_gibberish_abstains(text):
    result = analyze_text(text)
    assert result["status"] == "unsupported"
    assert result["stress_probability"] is None


@pytest.mark.parametrize("text", [
    "I had a peaceful afternoon and enjoyed a pleasant walk in the park with my friend.",
    "I am not stressed about the exam because I have prepared and feel ready for tomorrow.",
    "The person in this story says they are worried but I am quoting what they wrote.",
    "I think I am going to eat ice cream after finishing my work today.",
])
def test_ordinary_english_is_supported_without_claiming_negation_understanding(text):
    result = analyze_text(text)
    assert result["status"] == "ok"
    assert 0 <= result["stress_probability"] <= 1
    # No prescribed label: a bag-of-ngrams model cannot guarantee negation/sarcasm.
    assert "text" in " ".join(result["warnings"])


def test_does_not_load_user_supplied_serialized_models(tmp_path: Path):
    result = analyze_text("I feel worried about the work I need to finish tomorrow.", model_dir=tmp_path)
    assert result["status"] == "error"
    assert result["stress_probability"] is None


def test_missing_bundled_model_is_reported_without_traceback(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("stresslens.text_model.BUNDLED_MODEL_DIR", tmp_path)
    result = analyze_text("I feel worried about the work I need to finish tomorrow.")
    assert result["status"] == "error"
    assert result["stress_probability"] is None


def test_corrupt_model_fails_integrity_check_before_deserialization(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("stresslens.text_model.BUNDLED_MODEL_DIR", tmp_path)
    (tmp_path / "text_model.joblib").write_bytes(b"not a trusted model")
    (tmp_path / "text_model_metrics.json").write_text('{"artifact": {"sha256": "incorrect"}}', encoding="utf-8")
    result = analyze_text("I feel worried about the work I need to finish tomorrow.")
    assert result["status"] == "error"
    assert result["stress_probability"] is None
