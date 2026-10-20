"""Offline language-model summaries of supplied observations and curated research."""
from __future__ import annotations

import copy
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "qwen2.5-0.5b-instruct"
_INFERENCE_LOCK = threading.Lock()
_GRAMMAR = set("a an and are as at be been being but by can cannot could did do does due each for from had has have how if in is it its may might more no not of on only or other same several some than that the their these they this those to was were what when which while with without would yet also alone possible possibly explain explains explanation explanations observed observation measured measurement measurements movement movements shape shapes facial feature features change changes coefficient coefficients increased decreased higher lower person persons feel feels feeling stress level".split())
_LIMIT = "Facial movements alone do not establish stress or how a person feels."
_OBSERVATION_TERMS = frozenset(
    "observe observed observation observations measure measured measurement measurements "
    "coefficient coefficients reference references baseline baselines "
    "increase increased increases increasing decrease decreased decreases decreasing "
    "higher lower more less same reduced rose rising fell falling".split()
)


def _words(text):
    aliases = {"speech": "speaking", "speak": "speaking", "position": "pose",
               "positions": "pose", "smiling": "smile", "smiles": "smile"}
    return {aliases.get(word, word) for word in re.findall(r"[a-z]+", text.lower())}


def _grounded_alternative(text, card):
    """Reject new content words; this is a conservative filter, not entailment."""
    alternatives = " ".join(card.get("alternatives", []))
    anchors = _words(alternatives) - _GRAMMAR - {"expression", "changes", "movement", "movements", "related"}
    allowed = _GRAMMAR | _words(card["title"]) | _words(alternatives)
    words = _words(text)
    # Only the deterministic prefix may describe measurements or comparisons.
    # Reject such terms even when negated or copied from the card's title.
    return (bool(words & anchors) and words <= allowed
            and not words & _OBSERVATION_TERMS
            and not re.search(r"\b(?:stress|anxiety|mental|emotions?|feelings?|heart|physiological)\b", text.lower()))


@lru_cache(maxsize=1)
def _load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(MODEL_DIR, local_files_only=True,
                                               use_safetensors=True, dtype=torch.float32).eval()
    return tokenizer, model


def factual_fallback(cards):
    if not cards:
        return "No usable live face measurement is available."
    card = cards[0]
    return f"{card['observation']} {card['research_connection']} {card['limitation']}"


def check_generated_summary(text: str, cards: list[dict]) -> bool:
    """Conservative surface check; visible source cards remain authoritative."""
    if not isinstance(text, str) or not 20 <= len(text.strip()) <= 650:
        return False
    low = text.lower()
    banned = ("you are stressed", "you feel stressed", "you have", "you suffer", "diagnos", "depress",
              "mental illness", "stress level is", "stress score", "hidden stress", "hiding", "dishonest",
              "definitely", "proves", "confirms stress", "indicates stress", "you are anxious", "you need")
    if any(term in low for term in banned) or re.search(r"\d|%|https?://|\b(?:you|your|yours)\b", low):
        return False
    if re.search(r"\b(?:low|high|severe|moderate) stress\b|\b(?:person|participant) (?:is|feels|seems|may be|might be) (?:stressed|anxious|calm)\b", low):
        return False
    if re.search(r"\b(?:indicat\w*|reveal\w*|predict\w*|detect\w*|suggest\w*|reflect\w*|signal\w*)\b(?:\W+\w+){0,3}\W+(?:stress|anxiety|mental illness)\b", low):
        return False
    if not any(word in low for word in ("may", "might", "could", "cannot", "does not", "not enough", "not specific", "not prove", "not a")):
        return False
    context = " ".join(str(c.get(k, "")) for c in cards for k in ("title", "observation", "research_connection", "limitation")).lower()
    if len(cards) == 1:
        title = cards[0]["title"].lower()
        if "increased" in title and re.search(r"\b(?:decreased?|less|lower|reduced?)\b", low):
            return False
        if "decreased" in title and re.search(r"\b(?:increased?|more|higher|rose|rising)\b", low):
            return False
        if "increased" not in title and "decreased" not in title and re.search(r"\b(?:increased?|decreased?|more|less|higher|lower|reduced?)\b", low):
            return False
    if _words(text) - (_words(context) | _GRAMMAR | _words(" ".join(" ".join(c.get('alternatives', [])) for c in cards))):
        return False
    if not any(word in low and word in context for word in ("brow", "eye", "eyelid", "lip", "smil", "jaw", "face", "facial", "expression")):
        return False
    return True


def _source_candidates(card):
    phrases = [phrase.strip().rstrip(".") for phrase in card.get("alternatives", [])[:3]
               if phrase.strip()]
    phrases = [phrase[:1].lower() + phrase[1:] for phrase in phrases]
    choices = phrases + (["; ".join(phrases)] if len(phrases) > 1 else [])
    return list(dict.fromkeys(f"Possible explanations could be {choice}." for choice in choices))


def _candidate_token_constraint(sequences, prompt_length, eos_token_id):
    def allowed_tokens(_batch_id, input_ids):
        prefix = input_ids[prompt_length:].tolist()
        allowed = {
            eos_token_id if len(prefix) == len(sequence) else sequence[len(prefix)]
            for sequence in sequences if sequence[:len(prefix)] == prefix
        }
        if not allowed:
            raise ValueError("Generated prefix is outside the source candidates.")
        return sorted(allowed)
    return allowed_tokens


def generate_explanation(cards: list[dict]) -> dict:
    if not cards:
        return {"status": "unavailable", "text": factual_fallback(cards), "mode": "source_notes"}
    card = cards[0]
    # The model selects source wording; the observation and limits stay deterministic.
    candidates = _source_candidates(card)
    source_notes = "\n".join(candidates)
    instructions = "Choose one of the supplied sentences. Copy it exactly. Output only that sentence."
    began = time.perf_counter()
    try:
        import torch
        with _INFERENCE_LOCK:
            tokenizer, model = _load_model()
            sequences = [tokenizer.encode(candidate, add_special_tokens=False) for candidate in candidates]
            eos_token_id = tokenizer.eos_token_id
            if not sequences or any(not sequence for sequence in sequences) or not isinstance(eos_token_id, int):
                raise ValueError("Source candidates and an end token are required.")
            messages = [{"role": "system", "content": instructions},
                        {"role": "user", "content": source_notes[:2600]}]
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            tokens = tokenizer(prompt, return_tensors="pt", max_length=1024, truncation=True, add_special_tokens=False)
            prompt_length = tokens["input_ids"].shape[-1]
            with torch.inference_mode():
                generated = model.generate(
                    **tokens, max_new_tokens=max(map(len, sequences)) + 1, do_sample=False,
                    eos_token_id=eos_token_id,
                    prefix_allowed_tokens_fn=_candidate_token_constraint(sequences, prompt_length, eos_token_id),
                )
            draft = tokenizer.decode(generated[0][prompt_length:], skip_special_tokens=True).strip()
        text = f"{card['title']}. {draft} {_LIMIT}"
        if (draft not in candidates
                or not _grounded_alternative(draft, card)
                or not check_generated_summary(text, [card])):
            return {"status": "ok", "text": factual_fallback(cards), "mode": "source_notes",
                    "message": "The language-model draft did not pass the wording checks; showing source notes.",
                    "model": MODEL_ID, "elapsed_seconds": round(time.perf_counter() - began, 2)}
        return {"status": "ok", "text": text, "mode": "local_llm", "model": MODEL_ID,
                "generation_scope": "source_bounded_wording",
                "elapsed_seconds": round(time.perf_counter() - began, 2)}
    except (OSError, RuntimeError, ImportError, ValueError) as exc:
        return {"status": "ok", "text": factual_fallback(cards), "mode": "source_notes",
                "message": f"Local summarizer unavailable: {type(exc).__name__}. Showing source notes.",
                "elapsed_seconds": round(time.perf_counter() - began, 2)}


class LiveExplainer:
    """Single background worker; retains only the latest bounded text explanation."""
    def __init__(self, generate=generate_explanation, clock=time.monotonic):
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="StressLens-explainer")
        self._generate = generate
        self._clock = clock
        self._future = None
        self._fingerprint = None
        self._last_requested = -float("inf")
        self._result = None
        self._epoch = 0
        self._requested_epoch = 0

    @staticmethod
    def fingerprint(cards):
        return tuple((c["title"], c.get("source_id"),
                      re.sub(r"[+-]?\d+(?:\.\d+)?", "#", c.get("observation", "")))
                     for c in cards)

    def request(self, cards, force=False):
        if not cards or (self._future and not self._future.done()):
            return False
        fingerprint = self.fingerprint(cards)
        now = self._clock()
        if not force and (now - self._last_requested < 15 or fingerprint == self._fingerprint):
            return False
        self._fingerprint = fingerprint
        self._last_requested = now
        self._requested_epoch = self._epoch
        self._future = self._pool.submit(self._generate, copy.deepcopy(cards))
        return True

    def result(self, cards):
        fingerprint = self.fingerprint(cards)
        if self._future and self._future.done():
            try:
                value = self._future.result()
                self._result = value if self._requested_epoch == self._epoch else None
            except Exception:
                self._result = {"status": "error", "text": factual_fallback(cards), "mode": "source_notes"}
            self._future = None
        if not cards or fingerprint != self._fingerprint:
            return None
        if self._future:
            return {"status": "working", "text": "Preparing a local research explanation…", "mode": "local_llm"}
        result = copy.deepcopy(self._result)
        if result and result.get("mode") == "source_notes":
            result["text"] = factual_fallback(cards)
        return result

    def reset(self):
        self._epoch += 1
        self._fingerprint = None
        self._last_requested = -float("inf")
        self._result = None
        if self._future and self._future.cancel():
            self._future = None

    def close(self):
        self._pool.shutdown(wait=False, cancel_futures=True)
