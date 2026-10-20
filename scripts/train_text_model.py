r"""Train the local Dreaddit baseline once, using the authors' fixed test split.

Run from the project root: .venv\Scripts\python scripts/train_text_model.py
Only text is used as a predictor. No supplied sentiment, LIWC, or metadata
features are used. Raw data stays in the gitignored data directory.
"""

from __future__ import annotations

import hashlib
import io
import json
import platform
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = "https://www.cs.columbia.edu/~eturcan/data/dreaddit.zip"
SOURCE_SHA256 = "6c7d8859764231cca47410d6995d8941ac45b08a446a561923fd73b34f3f61cb"
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip().casefold()


def load_source() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    archive_path = data_dir / "dreaddit.zip"
    if not archive_path.exists():
        request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "StressLens-research-demo/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = response.read(MAX_ARCHIVE_BYTES + 1)
        if len(payload) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("Dataset archive exceeds the expected size limit.")
        if sha256(payload) != SOURCE_SHA256:
            raise RuntimeError("Dataset checksum changed; review the source before retraining.")
        archive_path.write_bytes(payload)
    payload = archive_path.read_bytes()
    if len(payload) > MAX_ARCHIVE_BYTES or sha256(payload) != SOURCE_SHA256:
        raise RuntimeError("Local dataset checksum differs from the verified authors' archive.")
    frames = []
    file_hashes = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        # Read only two exact members; never extract archive-controlled paths.
        for name in ("dreaddit-train.csv", "dreaddit-test.csv"):
            member = archive.getinfo(name)
            if member.file_size > MAX_ARCHIVE_BYTES:
                raise RuntimeError("Unexpected dataset member size.")
            raw = archive.read(name)
            file_hashes[name] = sha256(raw)
            frame = pd.read_csv(io.BytesIO(raw), usecols=["text", "label", "post_id"])
            if frame.isna().any().any() or not set(frame["label"].unique()) <= {0, 1}:
                raise RuntimeError("Dataset schema or labels differ from the expected release.")
            if not frame["text"].map(lambda text: bool(str(text).strip())).all():
                raise RuntimeError("Dataset contains empty text.")
            frames.append(frame)
    return frames[0], frames[1], file_hashes


def main() -> None:
    train, test, file_hashes = load_source()
    original_train_count = len(train)
    train_keys = train["text"].map(normalized_text)
    test_keys = test["text"].map(normalized_text)
    text_overlap = train_keys.isin(set(test_keys))
    post_overlap = train["post_id"].astype(str).isin(set(test["post_id"].astype(str)))
    overlap = text_overlap | post_overlap
    clean_train = train.loc[~overlap].copy()
    before_dedup = len(clean_train)
    clean_train = clean_train.loc[~clean_train["text"].map(normalized_text).duplicated()].copy()
    assert not set(clean_train["text"].map(normalized_text)) & set(test_keys)
    assert not set(clean_train["post_id"].astype(str)) & set(test["post_id"].astype(str))

    # Hyperparameters are fixed in advance, not selected on the supplied test set.
    model = Pipeline([
        ("tfidf", TfidfVectorizer(
            lowercase=True, ngram_range=(1, 2), min_df=2,
            max_features=30000, sublinear_tf=True, strip_accents="unicode",
        )),
        ("classifier", LogisticRegression(
            C=1.0, solver="liblinear", class_weight="balanced", max_iter=2000,
            random_state=42,
        )),
    ])
    model.fit(clean_train["text"], clean_train["label"])
    predictions = model.predict(test["text"])
    model_dir = ROOT / "models"
    model_dir.mkdir(exist_ok=True)
    model_path = model_dir / "text_model.joblib"
    joblib.dump(model, model_path, compress=3)
    metrics = {
        "schema_version": 1,
        "model_name": "Dreaddit TF-IDF + logistic regression baseline",
        "target": "Crowd annotators' binary judgement of stress expressed in Reddit text",
        "not_measured": ["clinical stress", "a person's stress level", "diagnosis", "facial stress"],
        "source": {
            "paper_url": "https://aclanthology.org/D19-6213/",
            "dataset_url": SOURCE_URL,
            "citation": "Turcan and McKeown (2019). Dreaddit: A Reddit Dataset for Stress Analysis in Social Media. LOuHI, pp. 97–107.",
            "archive_sha256": SOURCE_SHA256,
            "csv_sha256": file_hashes,
            "licensing_note": "Downloaded from the authors' public research release. The ZIP contains no separate dataset license; do not assume that the app's code license covers Reddit data or model redistribution.",
        },
        "training": {
            "random_seed": 42,
            "original_train_rows": original_train_count,
            "train_rows_removed_for_test_text_overlap": int(text_overlap.sum()),
            "train_rows_removed_for_test_post_overlap": int(post_overlap.sum()),
            "train_rows_removed_for_either_overlap": int(overlap.sum()),
            "train_rows_removed_for_within_train_duplicate_text": before_dedup - len(clean_train),
            "final_train_rows": len(clean_train),
            "train_class_counts": {str(k): int(v) for k, v in clean_train["label"].value_counts().sort_index().items()},
            "features": "TF-IDF words and word bigrams, min_df=2, max_features=30000, sublinear_tf=True; no metadata",
            "classifier": "LogisticRegression(C=1.0, solver=liblinear, class_weight=balanced, max_iter=2000)",
            "actual_vocabulary_size": len(model.named_steps["tfidf"].vocabulary_),
            "tuning": "No hyperparameter search or test-set tuning performed.",
        },
        "evaluation": {
            "split": "Authors' supplied test split, retained unchanged; overlapping posts/text removed from training",
            "test_rows": len(test),
            "test_class_counts": {str(k): int(v) for k, v in test["label"].value_counts().sort_index().items()},
            "accuracy": float(accuracy_score(test["label"], predictions)),
            "macro_f1": float(f1_score(test["label"], predictions, average="macro")),
            "binary_f1_stress_label": float(f1_score(test["label"], predictions, pos_label=1)),
            "majority_class_accuracy": float(test["label"].value_counts().max() / len(test)),
            "confusion_matrix_labels": ["0: no stress annotation", "1: stress annotation"],
            "confusion_matrix_rows_actual_columns_predicted": confusion_matrix(test["label"], predictions, labels=[0, 1]).tolist(),
            "classification_report": classification_report(test["label"], predictions, output_dict=True, zero_division=0),
            "within_test_duplicate_text_rows": int(test_keys.duplicated().sum()),
            "test_unique_posts": int(test["post_id"].nunique()),
            "scope": "Metrics describe this text classifier on this dataset, before app input guards; they do not validate face cues or multimodal stress estimation.",
        },
        "limitations": [
            "Crowd labels describe perceived stress in text; they are not clinical or self-reported stress measurements.",
            "English Reddit narratives differ from short personal check-ins, other languages and everyday conversation.",
            "Exact normalized text and post-ID overlap is removed from training; near-duplicate wording and shared authors cannot be ruled out (no author identifier supplied).",
            "Several test segments can come from one post, so rows are not fully independent.",
            "The model can learn topic and subreddit associations; no subgroup fairness or external validation has been performed.",
            "TF-IDF may misread negation, sarcasm, quoted speech and context. Term contributions are associations, not causes.",
            "predict_proba scores are uncalibrated model outputs, not probabilities that a person is stressed.",
            "No separate validation set, calibration, uncertainty interval or cross-domain test was used.",
        ],
        "artifact": {"file": model_path.name, "sha256": sha256(model_path.read_bytes())},
        "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__, "pandas": pd.__version__, "joblib": joblib.__version__},
        "trained_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (model_dir / "text_model_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"train_rows": len(clean_train), "test_rows": len(test), "removed_overlap": int(overlap.sum()), **{key: metrics["evaluation"][key] for key in ["accuracy", "macro_f1", "binary_f1_stress_label", "confusion_matrix_rows_actual_columns_predicted"]}}, indent=2))


if __name__ == "__main__":
    main()
