"""Private, offline inference for language resembling Dreaddit's stress labels.

This predicts text annotations, not a person's feelings or clinical condition.
The module neither stores input text nor makes network requests.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import joblib
from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

BUNDLED_MODEL_DIR = Path(__file__).resolve().parents[1] / "models"
MIN_WORDS = 8
MAX_CHARACTERS = 4000
DetectorFactory.seed = 42
_WORD = re.compile(r"[a-z]+(?:'[a-z]+)?", re.IGNORECASE)
_ENGLISH_ANCHORS = frozenset("i i'm i've i'd i'll me my myself we our us you your you're they their them he she his her it its the this that these those a an and or but because to of for with from am is are was were be been being have has had do does did don't not no will would can could should feel feeling felt today work about so very much really just at in on when how what as after before still now".split())
_BASE_WARNINGS = [
    "This model estimates a Reddit text annotation; it does not measure your stress level or diagnose a condition.",
    "The model score is uncalibrated and is not the probability that a person is stressed.",
]


def _result(status: str, explanation: str, warnings: list[str] | None = None) -> dict:
    return {
        "status": status,
        "label": None,
        "display_label": "No text result",
        "stress_probability": None,
        "top_terms": [],
        "explanation": explanation,
        "warnings": list(warnings or []),
    }


@lru_cache(maxsize=2)
def _load_checked_model(model_path: str, model_mtime: int, metadata_mtime: int):
    """Only called with the hard-coded bundled path; never accept uploaded pickle files."""
    path = Path(model_path)
    metadata = json.loads(path.with_name("text_model_metrics.json").read_text(encoding="utf-8"))
    expected = metadata["artifact"]["sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("Bundled model checksum mismatch")
    pipeline = joblib.load(path)
    if not {"tfidf", "classifier"} <= set(pipeline.named_steps):
        raise ValueError("Unexpected bundled model format")
    if list(pipeline.named_steps["classifier"].classes_) != [0, 1]:
        raise ValueError("Unexpected bundled model classes")
    return pipeline


def analyze_text(text: str, model_dir: Path | None = None) -> dict:
    """Return bounded, inspectable inference or an explicit abstention.

    ``stress_probability`` is retained as an API field for predict_proba output;
    the UI must call it an uncalibrated model score, not a health probability.
    ``model_dir`` can only identify this installation's bundled models folder.
    """
    if not isinstance(text, str):
        return _result("insufficient", "Enter an English description of your own situation.")
    text = unicodedata.normalize("NFKC", text).replace("’", "'").strip()
    if not text:
        return _result("insufficient", "Add at least eight English words describing the situation.")
    if len(text) > MAX_CHARACTERS:
        return _result("insufficient", f"Please shorten the text to {MAX_CHARACTERS:,} characters or fewer.")
    letters = [char for char in text if char.isalpha()]
    if letters and sum(char.isascii() for char in letters) / len(letters) < 0.65:
        return _result("unsupported", "The bundled text model supports English only. No score was produced.")
    words = _WORD.findall(text.lower())
    if len(words) < MIN_WORDS:
        return _result("insufficient", "Add at least eight English words; a short phrase gives too little context.")
    if len(set(words)) < 3:
        return _result("insufficient", "Use a few complete sentences rather than repeating one or two words.")
    warnings = list(_BASE_WARNINGS)
    try:
        languages = detect_langs(text)
        primary = languages[0]
        anchor_fraction = sum(word in _ENGLISH_ANCHORS for word in words) / len(words)
        # A few ordinary English sentences are misdetected by short-text detectors;
        # strong English function-word evidence prevents unnecessarily blocking them.
        if primary.lang != "en" and primary.prob >= 0.85 and anchor_fraction < 0.25:
            return _result("unsupported", "This appears to be another language or unclear text. Please write a few sentences in English.")
        if primary.lang != "en":
            warnings.append("Language detection is uncertain; English text is required for a useful result.")
    except LangDetectException:
        return _result("unsupported", "The text does not contain enough recognizable English for this model.")

    try:
        directory = BUNDLED_MODEL_DIR.resolve()
        if model_dir is not None and Path(model_dir).resolve() != directory:
            return _result("error", "Only the verified model bundled with this app can be loaded.")
        model_path = directory / "text_model.joblib"
        metadata_path = directory / "text_model_metrics.json"
        pipeline = _load_checked_model(str(model_path), model_path.stat().st_mtime_ns, metadata_path.stat().st_mtime_ns)
        vectorizer = pipeline.named_steps["tfidf"]
        classifier = pipeline.named_steps["classifier"]
        known_words = [word for word in words if word in vectorizer.vocabulary_]
        coverage = len(known_words) / len(words)
        if coverage < 0.35 or len(set(known_words)) < 3:
            return _result("unsupported", "Too little of this text matches the model's English vocabulary. Try a few complete sentences.")
        if coverage < 0.65:
            warnings.append("Many words are outside the training vocabulary; treat this result cautiously.")
        features = vectorizer.transform([text])
        if features.nnz == 0:
            return _result("unsupported", "The text has no recognizable model features. No score was produced.")
        score = float(classifier.predict_proba(features)[0, 1])
        label = "stress" if score >= 0.5 else "not_stress"
        display_label = "Language resembles stress-labelled examples" if score >= 0.5 else "Language resembles non-stress-labelled examples"
        if 0.4 <= score <= 0.6:
            warnings.append("The score is close to the decision boundary; this result is ambiguous.")
        if len(words) < 25:
            warnings.append("This is shorter than many training passages; more context may change the result.")
        # Explain the exact linear model using weighted features present in input.
        names = vectorizer.get_feature_names_out()
        contributions = features.multiply(classifier.coef_[0]).tocsr()
        order = sorted(zip(contributions.indices, contributions.data), key=lambda pair: abs(pair[1]), reverse=True)
        top_terms = [
            {"term": str(names[index]), "contribution": round(float(value), 4),
             "direction": "toward stress-labelled" if value > 0 else "toward non-stress-labelled"}
            for index, value in order[:6]
        ]
        return {
            "status": "ok", "label": label, "display_label": display_label, "stress_probability": score,
            "top_terms": top_terms,
            "explanation": "A local TF-IDF and logistic-regression model compares word patterns with crowd-labelled Reddit passages. Highlighted terms influenced this prediction; they are not evidence of a cause or a diagnosis.",
            "warnings": warnings,
            "word_count": len(words), "vocabulary_coverage": round(coverage, 3),
            "model": "Dreaddit TF-IDF + logistic regression",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, EOFError):
        return _result("error", "The bundled text model could not be loaded. Run scripts/train_text_model.py with this project's Python environment, then restart the app.")
