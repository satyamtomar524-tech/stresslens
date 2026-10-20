"""Research connections for measured shapes, without predicting a mental state.

The display threshold ranks noticeable model-coefficient changes only. It is
not learned from stress labels and must never be presented as a severity scale.
This module needs numeric snapshots only and performs no network or camera I/O.
"""
from __future__ import annotations

import math
from numbers import Real


CHANGE_DISPLAY_THRESHOLD = 0.15

_SOURCES = {
    "blasberg-2023": (
        "You look stressed: A pilot study on facial action unit activity in the context of psychosocial stress",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC10422124/",
    ),
    "giannakakis-2025": (
        "Stress recognition identifying relevant facial action units through explainable artificial intelligence and machine learning",
        "https://pubmed.ncbi.nlm.nih.gov/39608217/",
    ),
    "empathicschool-2025": (
        "A multimodal stress detection dataset with facial expressions and physiological signals",
        "https://www.nature.com/articles/s41597-025-05812-0",
    ),
}

_FEATURES = {
    "Brow lowering": {
        "source": "giannakakis-2025",
        "connection": (
            "A 58-person laboratory study found that combinations of facial action units "
            "differed between acute-stress tasks and neutral conditions. Relevant combinations "
            "depended on the task and personal reference; it did not establish a universal "
            "brow-lowering rule."
        ),
        "alternatives": ["Concentration or reading", "A deliberate expression", "Head pose or tracking changes"],
    },
    "Eye narrowing": {
        "source": "blasberg-2023",
        "connection": (
            "In a 62-person social-stress pilot, eyelid-tightener occurrences had different "
            "associations with subjective stress and heart measures. This eye-shape coefficient "
            "is only a visual analogy to that research."
        ),
        "alternatives": ["Bright light or screen glare", "Concentration", "A smile, head pose or tracking changes"],
    },
    "Lip pressing": {
        "source": "empathicschool-2025",
        "connection": (
            "EmpathicSchool examined lip-related movements alongside stress reports and "
            "physiological signals. Facial action patterns varied across participants; a "
            "lip-pressing coefficient alone was not validated as a stress measurement."
        ),
        "alternatives": ["Speaking or pausing between words", "A habitual or deliberate expression", "Head pose or tracking changes"],
    },
    "Smile shape": {
        "source": "blasberg-2023",
        "connection": (
            "Smiling movements occurred during the social-stress task in this pilot, "
            "with differences across participants and stress markers. A smile shape by "
            "itself does not establish how someone feels."
        ),
        "alternatives": ["Social smiling", "Enjoyment or a deliberate expression", "Speech-related mouth movement"],
    },
    "Eye closure": {
        "source": "blasberg-2023",
        "connection": (
            "The pilot examined several eye-related action units. Its eyelid-tightening "
            "findings do not validate this eye-closure coefficient as a stress indicator "
            "or a blink-rate measurement."
        ),
        "alternatives": ["An ordinary blink", "Looking down", "Glasses, head pose or tracking changes"],
    },
    "Jaw opening": {
        "source": "blasberg-2023",
        "connection": (
            "Jaw-drop occurrences were associated with heart-rate reactivity in the "
            "pilot's speaking and arithmetic context. That association does not turn "
            "this jaw-opening coefficient into a stress measurement."
        ),
        "alternatives": ["Speaking", "Yawning or a deliberate movement", "Head pose or tracking changes"],
    },
}

_LIMITATION = (
    "MediaPipe coefficients describe modeled facial shapes; they are not validated here "
    "as FACS action units or a person's psychological state. Research associations cannot "
    "establish the cause of this particular observation."
)
_THRESHOLD_NOTE = (
    " The 0.15 coefficient-change cutoff is an engineering display threshold, not a stress threshold."
)


def _coefficient(value: object) -> float | None:
    if not isinstance(value, Real) or isinstance(value, bool):
        return None
    number = float(value)
    return number if math.isfinite(number) and 0 <= number <= 1 else None


def _values(mapping: object) -> dict[str, float]:
    if not isinstance(mapping, dict):
        return {}
    result = {}
    for name in _FEATURES:
        number = _coefficient(mapping.get(name))
        if number is not None:
            result[name] = number
    return result


def _card(name: str, title: str, observation: str, *, compared: bool = False) -> dict:
    feature = _FEATURES[name]
    source_id = feature["source"]
    source_title, source_url = _SOURCES[source_id]
    return {
        "title": title,
        "observation": observation,
        "research_connection": feature["connection"],
        "alternatives": feature["alternatives"].copy(),
        "limitation": _LIMITATION + (_THRESHOLD_NOTE if compared else ""),
        "source_title": source_title,
        "source_url": source_url,
        "source_id": source_id,
    }


def research_insights(snapshot: dict) -> list[dict]:
    """Return at most two sourced cards from current, valid measurements.

    Comparisons use the actual coefficients and reference, not a supplied delta
    that might be stale or inconsistent. A single eye-closure sample or the
    numeric history is not treated as a measured blink rate or a mental state.
    """
    if not isinstance(snapshot, dict) or snapshot.get("status") != "ok":
        return []
    age = snapshot.get("frame_age_seconds")
    if age is not None and (
        not isinstance(age, Real) or isinstance(age, bool)
        or not math.isfinite(float(age)) or age < 0 or age > 2
    ):
        return []
    if "reference_progress" in snapshot:
        return []  # Capturing a reference is not an established comparison.
    groups = _values(snapshot.get("groups"))
    if not groups:
        return []

    reference = snapshot.get("baseline")
    if reference is None or reference == {}:
        ranked = sorted(groups, key=lambda name: (-groups[name], name))
        return [
            _card(
                name,
                f"Current {name.lower()} shape",
                f"{name} coefficient is {groups[name]:.2f} now. "
                "No reference is available, so an increase or decrease cannot be inferred.",
            )
            for name in ranked[:2]
        ]

    baseline = _values(reference)
    comparable = {name: groups[name] - baseline[name] for name in groups if name in baseline}
    if not comparable:
        return []
    ranked = sorted(comparable, key=lambda name: (-abs(comparable[name]), name))
    noticeable = [
        name for name in ranked
        if abs(comparable[name]) + 1e-12 >= CHANGE_DISPLAY_THRESHOLD
    ]
    if not noticeable:
        name = ranked[0]
        return [_card(
            name,
            "Current measurements near the reference",
            f"Largest comparable change: {name.lower()}, {comparable[name]:+.2f} "
            f"({groups[name]:.2f} now; {baseline[name]:.2f} reference). "
            "All comparable changes are below the 0.15 display cutoff. "
            "This describes these measurements, not low stress or calmness.",
            compared=True,
        )]
    return [
        _card(
            name,
            f"{name} coefficient {'increased' if comparable[name] > 0 else 'decreased'}",
            f"{name} coefficient is {groups[name]:.2f} now versus {baseline[name]:.2f} "
            f"in the reference: {comparable[name]:+.2f} "
            f"({'higher' if comparable[name] > 0 else 'lower'}).",
            compared=True,
        )
        for name in noticeable[:2]
    ]
