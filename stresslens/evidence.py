"""Curated evidence lookup and deterministic, nonclinical result explanations.

The searchable material is our brief source notes, not the full papers or books.
Retrieval scores measure word overlap and are not scientific confidence scores.
No user text, images, or search queries are transmitted by this module.
"""

from __future__ import annotations

import math
import re
from numbers import Real


SOURCES = [
    {
        "id": "giannakakis-2025",
        "title": "Stress recognition identifying relevant facial action units through explainable artificial intelligence and machine learning",
        "year": 2025,
        "url": "https://pubmed.ncbi.nlm.nih.gov/39608217/",
        "kind": "Primary research: facial action combinations",
        "summary": "A laboratory study of 58 participants compared facial action patterns across stress and neutral tasks. Relevant combinations depended on the task and personalized references.",
        "limitations": "Task-specific results do not validate a universal facial stress rule. This app has not reproduced that trained classifier; MediaPipe blendshapes are a different measurement.",
    },
    {
        "id": "empathicschool-2025",
        "title": "A multimodal stress detection dataset with facial expressions and physiological signals",
        "year": 2025,
        "url": "https://www.nature.com/articles/s41597-025-05812-0",
        "kind": "Primary research: facial and physiological dataset",
        "summary": "EmpathicSchool records 30 participants during laboratory tasks, including facial observations, physiological signals and acute-stress reports. Facial patterns vary between people, and multiple signals were studied together.",
        "limitations": "The paper concerns acute stress in a controlled setting. Its data currently require approved access. Neither a single lip movement nor this app's research analogy establishes a person's stress level.",
    },
    {
        "id": "blasberg-2023",
        "title": "You look stressed: A pilot study on facial action unit activity in the context of psychosocial stress",
        "year": 2023,
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10422124/",
        "kind": "Primary research: laboratory pilot",
        "summary": (
            "In 62 participants, facial action unit activity during a social stress task "
            "was associated with cortisol, heart measures and subjective stress. "
            "Different stress markers had different facial associations; smiling also "
            "occurred during stress. Eyelid tightening was one candidate signal."
        ),
        "limitations": (
            "Correlational pilot without a non-stressed control group. Context and "
            "individual differences matter. These findings do not validate a stress "
            "percentage from a photo or a universal facial rule."
        ),
    },
    {
        "id": "jeon-2021",
        "title": "Deep-Learning-Based Stress Recognition with Spatial-Temporal Facial Information",
        "year": 2021,
        "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC8625615/",
        "kind": "Primary research: video classification",
        "summary": (
            "A study of 50 people used two-second facial video clips and three "
            "experimental stress classes. Participant-disjoint evaluation achieved "
            "66.84% accuracy in that dataset. The authors describe identity leakage "
            "and speaking versus non-speaking conditions as evaluation concerns."
        ),
        "limitations": (
            "Laboratory classification is not a clinical measurement or a validated "
            "score for a new webcam user. Split by participant before forming clips; "
            "frames from the same person must not leak into testing."
        ),
    },
    {
        "id": "facs-official",
        "title": "Facial Action Coding System (FACS): official manual reference",
        "year": "Undated",
        "url": "https://www.paulekman.com/facial-action-coding-system/",
        "kind": "Official manual reference",
        "summary": (
            "FACS describes visible facial movements using anatomically based "
            "action units. The official manual provides criteria and examples "
            "for observing and coding those movements."
        ),
        "limitations": (
            "This app includes a short description of the official reference page, "
            "not the licensed manual. Its face blendshape coefficients are not "
            "certified FACS action unit coding or psychological stress measurements."
        ),
    },
    {
        "id": "ubfc-phys-2021",
        "title": "UBFC-Phys: A Multimodal Database For Psychophysiological Studies Of Social Stress",
        "year": 2021,
        "url": "https://sites.google.com/view/ybenezeth/ubfc-phys",
        "kind": "Dataset creators' official project page",
        "summary": (
            "UBFC-Phys contains recordings of 56 participants completing rest, "
            "speech and arithmetic tasks. It combines video, blood volume pulse "
            "and electrodermal activity with self-reported anxiety before and "
            "after the experiment."
        ),
        "limitations": (
            "Task conditions, anxiety ratings and physiological signals are "
            "different measurements. The dataset does not establish a universal "
            "stress scale from a photograph. This app has not been trained or "
            "validated on UBFC-Phys."
        ),
    },
    {
        "id": "dreaddit-2019",
        "title": "Dreaddit: A Reddit Dataset for Stress Analysis in Social Media",
        "year": 2019,
        "url": "https://aclanthology.org/D19-6213/",
        "kind": "Primary research: text dataset",
        "summary": (
            "Turcan and McKeown introduce a corpus from five categories of "
            "Reddit communities. About 3,500 segments from approximately 3,000 "
            "posts were annotated by crowd workers for stress analysis, within "
            "a larger collection of roughly 190,000 posts."
        ),
        "limitations": (
            "Crowd labels describe perceived stress in language, not a clinical "
            "diagnosis or the writer's measured stress level. Performance on "
            "Reddit does not establish reliability for short personal messages, "
            "other languages or facial video."
        ),
    },
]

_STOP_WORDS = frozenset(
    "a an and are as at be by can did do does for from had has have how i in is it "
    "its me my of on or our that the their them these they this to was we were "
    "what when where which who why will with would you your".split()
)
_ALIASES = {
    "facial": "face", "faces": "face", "videos": "video", "photos": "photo",
    "photograph": "photo", "photographs": "photo", "images": "image",
    "smile": "smiling", "smiles": "smiling", "au": "units", "aus": "units",
    "participants": "participant", "subjects": "participant",
    "subject": "participant", "datasets": "dataset", "scores": "score",
    "stressed": "stress", "stressful": "stress", "levels": "level",
}


def _tokens(text: str) -> set[str]:
    return {
        _ALIASES.get(token, token)
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOP_WORDS and len(token) > 1
    }


def search_evidence(query: str, limit: int = 3) -> list[dict]:
    """Return matching curated notes with a word-relevance ``score``.

    Empty, stop-word-only and unrelated queries return an empty list. Scores
    rank this small collection only; they do not measure evidence quality or
    answer correctness. Returned dictionaries are copies of the source records.
    """
    query_tokens = _tokens(query)
    if not query_tokens or limit <= 0:
        return []
    documents = [
        _tokens(" ".join(str(source[key]) for key in
                         ("id", "title", "summary", "limitations", "kind")))
        for source in SOURCES
    ]
    weights = {
        token: 1 + math.log((len(documents) + 1) /
                            (1 + sum(token in document for document in documents)))
        for token in query_tokens
    }
    denominator = sum(weights.values())
    ranked = []
    for source, document in zip(SOURCES, documents):
        shared = query_tokens & document
        if shared:
            score = sum(weights[token] for token in shared) / denominator
            ranked.append({**source, "score": round(score, 6)})
    return sorted(ranked, key=lambda item: (-item["score"], item["id"]))[:limit]


def _valid_probability(value: object) -> bool:
    return (
        isinstance(value, Real) and not isinstance(value, bool)
        and math.isfinite(float(value)) and 0 <= value <= 1
    )


def build_summary(
    text_result: dict | None,
    face_result: dict | None,
    self_report: int | None,
) -> str:
    """Describe separate observations without diagnosing or combining scores."""
    parts = []
    if self_report is None:
        parts.append("No self-reported stress rating was provided.")
    elif isinstance(self_report, int) and not isinstance(self_report, bool) and 0 <= self_report <= 10:
        parts.append(f"Your self-reported stress is {self_report}/10. This is your own rating.")
    else:
        parts.append("The self-reported rating is invalid; use a whole number from 0 to 10.")

    if not text_result:
        parts.append("No text analysis was provided.")
    elif str(text_result.get("status", "")).lower() not in {"ok", "success"}:
        parts.append("Text analysis was unavailable; no language result is inferred.")
    else:
        label = str(text_result.get("label", "")).lower().replace("-", "_").replace(" ", "_")
        if label in {"stress", "stressed", "stress_related"}:
            text_note = "The text model classified the wording as stress-related."
        elif label in {"not_stress", "no_stress", "non_stress", "not_stressed", "non_stress_related"}:
            text_note = "The text model classified the wording as not stress-related."
        else:
            text_note = "The text model returned an unrecognized class label."
        probability = text_result.get("stress_probability")
        if _valid_probability(probability):
            text_note += f" Its uncalibrated stress-class score is {float(probability):.3f}."
        text_note += " This describes language patterns, not your psychological stress level."
        parts.append(text_note)

    if not face_result:
        parts.append("No face analysis was provided.")
    else:
        status = str(face_result.get("status", "")).lower()
        face_frames = face_result.get("face_frames", 0)
        total_frames = face_result.get("frames_analyzed", 0)
        valid_counts = (
            isinstance(face_frames, int) and not isinstance(face_frames, bool)
            and isinstance(total_frames, int) and not isinstance(total_frames, bool)
            and 0 <= face_frames <= total_frames
        )
        if status in {"no_face", "no_faces"} or (
            status in {"ok", "success"} and valid_counts and face_frames == 0
        ):
            parts.append("No detectable face was found in the analyzed input; no facial interpretation is available.")
        elif status not in {"ok", "success"} or not valid_counts:
            parts.append("Face analysis was unavailable or incomplete; no facial interpretation is available.")
        else:
            unit = "frame" if total_frames == 1 else "frames"
            parts.append(
                f"Face measurements were available in {face_frames} of {total_frames} analyzed {unit}. "
                "Facial landmarks and blendshape coefficients describe visible geometry and movement; "
                "they do not determine your stress level."
            )

    parts.append(
        "These observations are shown separately. This prototype has no validated combined "
        "stress score and does not diagnose health conditions or determine whether words and feelings match."
    )
    return "\n\n".join(parts)
