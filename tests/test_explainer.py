import time
import threading
import sys
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import numpy as np

from stresslens.explainer import MODEL_DIR, LiveExplainer, _grounded_alternative, check_generated_summary, factual_fallback, generate_explanation
from stresslens.insights import research_insights

EYE_CANDIDATES = (
    "Possible explanations could be bright light or screen glare.",
    "Possible explanations could be concentration.",
    "Possible explanations could be a smile, head pose or tracking changes.",
    "Possible explanations could be bright light or screen glare; concentration; a smile, head pose or tracking changes.",
)


def cards():
    return research_insights({"status": "ok", "groups": {"Eye narrowing": 0.6}, "baseline": {"Eye narrowing": 0.2}})


def test_summary_rejects_diagnosis_unfounded_numbers_and_unqualified_claims():
    evidence = cards()
    assert not check_generated_summary("You are stressed and your stress score is 80 percent.", evidence)
    assert not check_generated_summary("You have depression and should see a doctor.", evidence)
    assert not check_generated_summary("Eye narrowing indicates stress.", evidence)
    assert not check_generated_summary("Your eyes may mean you are under high stress.", evidence)
    assert not check_generated_summary("The person might be stressed based on eye narrowing.", evidence)
    assert not check_generated_summary("Eye narrowing may indicate stress.", evidence)
    assert not check_generated_summary("Brow movements could reveal a person's stress.", evidence)
    assert not check_generated_summary("Eye narrowing has increased, which may be due to media effects on human perception.", evidence)
    assert not check_generated_summary("Eye narrowing decreased. This may be due to concentration.", evidence)
    no_reference = research_insights({"status": "ok", "groups": {"Eye narrowing": 0.6}})
    assert not check_generated_summary("Eye narrowing increased and may be due to bright light.", no_reference)
    assert check_generated_summary("Eye narrowing may be due to bright light; it does not establish a person's stress level.", evidence)


def test_missing_observation_has_no_generated_interpretation():
    assert generate_explanation([])["status"] == "unavailable"
    assert factual_fallback([]) == "No usable live face measurement is available."


def test_alternative_filter_rejects_invented_explanations_and_health_claims():
    card = cards()[0]
    assert _grounded_alternative("Bright light or screen glare could explain the eye narrowing.", card)
    assert not _grounded_alternative("Media effects on human perception may explain eye narrowing.", card)
    assert not _grounded_alternative("Concentration may mean stress is high.", card)
    brow = research_insights({"status": "ok", "groups": {"Brow lowering": 0.6}})[0]
    assert _grounded_alternative("Head pose or tracking changes could explain brow lowering.", brow)


@pytest.mark.parametrize("draft", [
    "Eye narrowing may not have increased; bright light could explain the shape.",
    "Eye narrowing may not have decreased; bright light could explain the shape.",
    "Eye narrowing may be higher due to bright light.",
    "Eye narrowing may be lower due to bright light.",
    "More eye narrowing may be due to bright light.",
    "Eye narrowing may be the same due to bright light.",
    "Eye narrowing coefficients may be due to bright light.",
    "Eye narrowing may not be measured due to bright light.",
])
def test_alternative_filter_rejects_measurement_claims(draft):
    assert not _grounded_alternative(draft, cards()[0])


@pytest.mark.parametrize("draft", [
    "Measurements may not be near the reference due to bright light.",
    "The reference may be due to bright light.",
])
def test_alternative_filter_rejects_reinterpreting_a_reference(draft):
    evidence = research_insights({"status": "ok", "groups": {"Eye narrowing": 0.21},
                                  "baseline": {"Eye narrowing": 0.2}})
    assert not _grounded_alternative(draft, evidence[0])


@pytest.fixture
def local_generation(monkeypatch):
    # Replace only local model loading/inference; exercise the real output checks.
    tokenizer = Mock()
    tokenizer.apply_chat_template.return_value = "synthetic prompt"
    tokenizer.return_value = {"input_ids": SimpleNamespace(shape=(1, 1))}
    tokenizer.eos_token_id = 0
    tokenizer.encode.side_effect = lambda text, **kwargs: [ord(char) for char in text]
    model = Mock()
    model.generate.return_value = [[999, 1]]
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(inference_mode=nullcontext))
    monkeypatch.setattr("stresslens.explainer._load_model", lambda: (tokenizer, model))
    return SimpleNamespace(tokenizer=tokenizer, model=model)


@pytest.mark.parametrize("current, reference, draft, expected_observation", [
    (0.6, 0.2, "Eye narrowing may not have increased; bright light could explain the shape.",
     "Eye narrowing coefficient is 0.60 now versus 0.20 in the reference: +0.40 (higher)."),
    (0.2, 0.6, "Eye narrowing may not have decreased; bright light could explain the shape.",
     "Eye narrowing coefficient is 0.20 now versus 0.60 in the reference: -0.40 (lower)."),
])
def test_generated_negated_direction_uses_factual_fallback(
        local_generation, current, reference, draft, expected_observation):
    local_generation.tokenizer.decode.return_value = draft
    evidence = research_insights({"status": "ok", "groups": {"Eye narrowing": current},
                                  "baseline": {"Eye narrowing": reference}})
    result = generate_explanation(evidence)
    assert result["mode"] == "source_notes"
    assert result["text"].startswith(expected_observation)
    assert draft not in result["text"]


def test_selected_source_wording_keeps_the_deterministic_observation(local_generation):
    local_generation.tokenizer.decode.return_value = EYE_CANDIDATES[0]
    result = generate_explanation(cards())
    assert result["mode"] == "local_llm"
    assert result["generation_scope"] == "source_bounded_wording"
    assert result["text"].startswith("Eye narrowing coefficient increased. " + EYE_CANDIDATES[0])
    assert result["text"].endswith("Facial movements alone do not establish stress or how a person feels.")


def test_model_receives_alternatives_without_measurement_claims(local_generation):
    local_generation.tokenizer.decode.return_value = EYE_CANDIDATES[0]
    generate_explanation(cards())
    messages = local_generation.tokenizer.apply_chat_template.call_args.args[0]
    supplied_notes = next(message["content"] for message in messages if message["role"] == "user").lower()
    assert "bright light or screen glare" in supplied_notes
    assert "concentration" in supplied_notes
    assert "a smile, head pose or tracking changes" in supplied_notes
    assert "coefficient" not in supplied_notes
    assert "increased" not in supplied_notes


def test_decoder_only_allows_complete_source_candidates(local_generation):
    local_generation.tokenizer.decode.return_value = EYE_CANDIDATES[0]
    generate_explanation(cards())
    options = local_generation.model.generate.call_args.kwargs
    allowed_tokens = options.get("prefix_allowed_tokens_fn")
    assert callable(allowed_tokens)
    expected = {tuple(map(ord, candidate)) for candidate in EYE_CANDIDATES}
    completed, pending = set(), [()]
    while pending:
        prefix = pending.pop()
        allowed = allowed_tokens(0, np.array([999, *prefix]))
        assert ord("#") not in allowed
        for token in allowed:
            if token == 0:
                assert prefix in expected  # EOS cannot truncate a candidate.
                completed.add(prefix)
            else:
                assert len(prefix) < max(map(len, expected))
                pending.append((*prefix, token))
    assert completed == expected
    assert options["eos_token_id"] == 0
    assert options["max_new_tokens"] >= max(map(len, expected)) + 1
    with pytest.raises(ValueError):
        allowed_tokens(0, np.array([999, ord("#")]))


@pytest.mark.parametrize("draft", [
    "Possible explanations could be eye strain.",
    "Bright light or screen glare could explain the eye narrowing.",
])
def test_off_list_output_is_rejected_if_a_model_bypasses_the_token_constraint(local_generation, draft):
    local_generation.tokenizer.decode.return_value = draft
    result = generate_explanation(cards())
    assert result["mode"] == "source_notes"
    assert draft not in result["text"]


def test_installed_chat_model_generates_a_grounded_offline_explanation():
    if not (MODEL_DIR / "model.safetensors").exists():
        pytest.skip("Optional chat model absent; run scripts/setup_explainer.py.")
    result = generate_explanation(cards())
    assert result["status"] == "ok"
    assert result["mode"] == "local_llm", result
    assert result["generation_scope"] == "source_bounded_wording"
    assert result["text"] in {
        f"Eye narrowing coefficient increased. {candidate} Facial movements alone do not establish stress or how a person feels."
        for candidate in EYE_CANDIDATES
    }
    assert check_generated_summary(result["text"], cards())


def test_background_explainer_is_bounded_and_does_not_reuse_opposite_changes():
    calls = []
    def generate(evidence):
        calls.append(evidence)
        return {"status": "ok", "text": "Eye narrowing may have several explanations.", "mode": "local_llm"}
    worker = LiveExplainer(generate=generate)
    evidence = cards()
    try:
        assert worker.request(evidence)
        deadline = time.monotonic() + 3
        result = worker.result(evidence)
        while result and result["status"] == "working" and time.monotonic() < deadline:
            time.sleep(0.01)
            result = worker.result(evidence)
        assert result["status"] == "ok"
        assert len(calls) == 1
        assert not worker.request(evidence)
        opposite = research_insights({"status": "ok", "groups": {"Eye narrowing": 0.2}, "baseline": {"Eye narrowing": 0.6}})
        assert worker.result(opposite) is None
        assert worker.result([]) is None
    finally:
        worker.close()


def test_source_note_fallback_uses_current_values_and_reset_drops_old_result():
    worker = LiveExplainer(generate=lambda evidence: {"status": "ok", "text": factual_fallback(evidence), "mode": "source_notes"})
    initial = cards()
    try:
        worker.request(initial)
        deadline = time.monotonic() + 3
        result = worker.result(initial)
        while result and result["status"] == "working" and time.monotonic() < deadline:
            time.sleep(0.01)
            result = worker.result(initial)
        assert "0.60 now" in result["text"]
        current = research_insights({"status": "ok", "groups": {"Eye narrowing": 0.9}, "baseline": {"Eye narrowing": 0.2}})
        assert "0.90 now" in worker.result(current)["text"]
        assert "0.60 now" not in worker.result(current)["text"]
        worker.reset()
        assert worker.result(current) is None
    finally:
        worker.close()


def test_reset_discards_a_running_previous_session_explanation():
    began = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    def generate(evidence):
        began.set()
        release.wait(3)
        finished.set()
        return {"status": "ok", "text": "Previous session's explanation", "mode": "local_llm"}
    worker = LiveExplainer(generate=generate)
    evidence = cards()
    try:
        assert worker.request(evidence)
        assert began.wait(3)
        worker.reset()
        assert worker.result(evidence) is None
        release.set()
        assert finished.wait(3)
        deadline = time.monotonic() + 3
        while worker._future and not worker._future.done() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert worker.result(evidence) is None
    finally:
        release.set()
        worker.close()
