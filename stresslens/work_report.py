"""A transient view of one work clock and its explicitly associated answers."""
import json

from stresslens.personal_patterns import summarize_checkins
from stresslens.output_summaries import work_overview
from stresslens.wellbeing_store import merge_checkins


def build_work_report(work, records):
    # Deliberately accepts current ledger records only, never restored history.
    selected = [row for row in merge_checkins([], records)
                if work.session_id is not None and row["session_id"] == work.session_id]
    summary = summarize_checkins(selected)
    counts = []
    for field, label in (("stress_counts", "Stress"), ("clarity_counts", "Clarity")):
        total = {}
        for day in summary["by_day"]:
            for choice, count in day[field].items():
                total[choice] = total.get(choice, 0) + count
        counts.extend({"answer": f"{label}: {choice.title()}", "count": count}
                      for choice, count in total.items())
    seconds = work.elapsed_seconds
    return {"schema": "stresslens-work-report/1", "session_id": work.session_id,
            "state": work.state, "started_at": work.started_at.isoformat() if work.started_at else None,
            "ended_at": work.ended_at.isoformat() if work.ended_at else None,
            "active_seconds": seconds, "checkins": selected, "answer_counts": counts,
            "explanation": work_overview(work.state, seconds, summary),
            "scope": "Current or most recently ended work session; current ledger answers explicitly linked to its ID only. "
                     "Closing answers require explicit selection and keep their actual answer time. "
                     "Older, standalone and restored history are excluded. Active time is not camera time or observation span."}


def work_report_json(report):
    return json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2)


def work_report_text(report):
    # Include the same complete payload, so no clarity, timestamps or scope are lost.
    return "StressLens work-session report\n" + report["explanation"] + "\n" + report["scope"] + "\n\n" + work_report_json(report)
