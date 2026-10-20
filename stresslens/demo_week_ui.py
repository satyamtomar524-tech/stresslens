"""Read-only fictional presentation, separate from all personal controllers and I/O."""
from html import escape

import pandas as pd
import streamlit as st


def set_demo_mode(enabled):
    if enabled:
        st.query_params["example"] = "fictional-week"
    else:
        st.query_params.pop("example", None)


def keep_real_widget_choices():
    # Streamlit cleans up absent widgets. Retain choices while their UI is absent,
    # without rendering personal services, restoring history or touching the clock.
    buttons = {"report_import_preview", "report_import_add", "report_clear",
               "report_download_json", "report_download_txt"}
    choices = {"wellbeing_reminders", "wellbeing_break_minutes", "wellbeing_keep_history",
               "face_sdk_metrics_opt_in", "analysis_input_choice"}
    prefixes = ("wellbeing_stress_", "wellbeing_clarity_", "text_", "include_", "rating_", "report_")
    for key in list(st.session_state):
        if key in buttons or key.startswith("report_import_file_"):
            continue
        if key in choices or key.startswith(prefixes):
            value = st.session_state[key]
            if value is None or type(value) in (str, bool, int, float):
                st.session_state[key] = value


def render_count_bars(frame, labels, colors):
    """Responsive categorical bars with readable labels and no chart export tools."""
    legend = "".join(f'<span><i style="background:{color}"></i>{escape(label)}</span>'
                     for label, color in zip(labels.values(), colors, strict=True))
    rows = []
    for _, row in frame.iterrows():
        total = int(row["Check-ins"])
        description = str(row["UTC day"]) + ": " + ", ".join(
            f"{label} {int(row[key])} of {total}" for key, label in labels.items())
        segments = "".join(f'<span style="flex:{int(row[key])};background:{color}" '
                            f'title="{escape(label)}: {int(row[key])} of {total}"></span>'
                            for (key, label), color in zip(labels.items(), colors, strict=True) if row[key])
        rows.append(f'<div class="fictional-bar-row" role="listitem" aria-label="{escape(description)}">'
                    f'<span>{escape(str(row["UTC day"])[5:])}</span>'
                    f'<div class="fictional-bar" aria-hidden="true">{segments}</div><span>{total}</span></div>')
    st.markdown('<div class="fictional-chart"><div class="fictional-legend">' + legend +
                '</div><div role="list" aria-label="Fictional counts by UTC day">' + "".join(rows) + '</div></div>',
                unsafe_allow_html=True)


def render_demo_week(week, *, summarize):
    keep_real_widget_choices()
    with st.container(key="fictional_banner"):
        st.info("Fictional example — not your data")
        st.button("Return to my session", on_click=set_demo_mode, args=(False,),
                  type="primary", key="fictional_return")
    st.header(week["title"])
    st.caption(f"{week['start_date']} to {week['end_date']} · UTC · two invented check-ins per day. "
               "This example is view-only and is never saved to your history or session report.")
    summary = summarize(week["records"])
    count, days = st.columns(2)
    count.metric("Example check-ins", summary["total_checkins"])
    days.metric("Example days", summary["days_with_checkins"])
    stress = pd.DataFrame([{"UTC day": row["date"], "Check-ins": row["checkin_count"],
                            **row["stress_counts"]} for row in summary["by_day"]])
    clarity = pd.DataFrame([{"UTC day": row["date"], "Check-ins": row["checkin_count"],
                             **row["clarity_counts"]} for row in summary["by_day"]])
    total = summary["total_checkins"]
    stress_labels = {"none": "None", "low": "Low", "high": "High", "unsure": "Unsure",
                     "skipped": "Skipped", "expired": "Expired"}
    clarity_labels = {"clear": "Clear", "mixed": "Mixed", "foggy": "Foggy", "unsure": "Unsure", "skipped": "Skipped"}
    st.subheader("Stress choices in the example")
    answered = int(stress[["none", "low", "high"]].sum().sum())
    st.caption(f"Answered stress: {answered}/{total} check-ins. Unsure: {stress['unsure'].sum()}/{total}; "
               f"skipped: {stress['skipped'].sum()}/{total}; expired: {stress['expired'].sum()}/{total}. "
               "Each bar counts that day's two check-ins; missing answers are separate categories.")
    render_count_bars(stress, stress_labels, ["#087e8b", "#557ba1", "#ad624b", "#8b78a2", "#8d969e", "#bec6ce"])
    with st.expander("View exact stress counts"):
        st.caption("Two example check-ins per row. Scroll the count table sideways on a narrow screen.")
        with st.container(key="fictional_stress_counts"):
            st.table(stress.rename(columns=stress_labels).set_index("UTC day"))
    st.subheader("Clarity choices in the example")
    provided = int(clarity[["clear", "mixed", "foggy"]].sum().sum())
    st.caption(f"Clarity supplied: {provided}/{total} check-ins. Unsure: {clarity['unsure'].sum()}/{total}; "
               f"skipped: {clarity['skipped'].sum()}/{total}. Blank clarity is skipped, never clear by default.")
    render_count_bars(clarity, clarity_labels, ["#087e8b", "#557ba1", "#ad8460", "#8b78a2", "#8d969e"])
    with st.expander("View exact clarity counts"):
        st.caption("Two example check-ins per row. Scroll the count table sideways on a narrow screen.")
        with st.container(key="fictional_clarity_counts"):
            st.table(clarity.rename(columns=clarity_labels).set_index("UTC day"))
    with st.expander("What this shows · what has been checked"):
        st.write("These are invented categorical answers, showing how daily counts and missing responses look. "
                 "They do not establish a trend, explain a cause or show that taking a break changes stress.")
        st.write("Software checks cover timer controls, explicit answers, storage choices and separation of this example "
                 "from a personal session. Local browser checks cover the interface. Those checks do not validate "
                 "stress prediction, scientific accuracy or physical-camera performance.")
    st.caption("Fictional example — not your data. Return to my session above to continue your own work clock.")
