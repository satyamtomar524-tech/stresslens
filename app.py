"""Run with: .venv/Scripts/python.exe -m streamlit run app.py"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from stresslens.evidence import SOURCES, build_summary, search_evidence
from stresslens.face import analyze_image, analyze_video, feature_groups, serializable_result
from stresslens.text_model import analyze_text
from stresslens.live_ui import render_live_camera
from stresslens.charts import render_feature_trend
from stresslens.session_ui import ensure_report_controller
from stresslens.wellbeing_ui import render_wellbeing
from stresslens.personal_patterns import summarize_checkins
from stresslens.demo_week import get_demo_week
from stresslens.demo_week_ui import render_demo_week, set_demo_mode
from stresslens.personal_photo import commit_analysis, get_photo, photo_revision
from stresslens.photo_ui import render_photo_panel
from stresslens.output_summaries import analysis_overview

ROOT = Path(__file__).resolve().parent
DEMO_TEXT = (
    "I have been feeling overwhelmed by everything I need to finish this week. "
    "I keep worrying about the deadlines and I cannot relax or sleep properly. "
    "It feels like there is too much pressure on me right now."
)

st.set_page_config(page_title="StressLens · workday companion", page_icon="◉", layout="wide")
st.markdown(f"<style>{(ROOT / 'assets' / 'app.css').read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

st.title("StressLens")
if st.query_params.get("example") == "fictional-week":
    render_demo_week(get_demo_week(), summarize=summarize_checkins)
    st.stop()

st.markdown('<div class="intro">A workday companion for check-ins, breaks and reflection. Start with the camera off.</div>', unsafe_allow_html=True)
st.caption("Work session is ready below. Camera, text analysis and research are optional tools in the other views.")

live_tab, analyze_tab, research_tab, model_tab, work_tab = st.tabs(
    ["Live camera", "Upload & text", "Sources", "About", "Work session"], default="Work session"
)

with live_tab:
    face_sdk_metrics_opt_in = render_live_camera()


def render_source(source):
    with st.expander(f"{source['title']} · {source['year']}"):
        st.caption(source["kind"])
        st.write(source["summary"])
        st.write("**Limits:** " + source["limitations"])
        st.link_button("Open original source", source["url"])


with analyze_tab:
    st.subheader("Explore your inputs")
    st.caption("For personal exploration and research. Facial measurements do not determine stress or reveal hidden feelings.")
    if st.session_state.get("analysis_input_choice") == "Example inputs":
        st.session_state["analysis_input_choice"] = "Fictional text example"
        st.session_state.pop("analysis", None)
    choice = st.radio("Start with", ["My inputs", "Fictional text example"], horizontal=True,
                      key="analysis_input_choice", index=0)
    if st.session_state.get("input_choice") != choice:
        st.session_state.pop("analysis", None)
        st.session_state["input_choice"] = choice
    demo = choice == "Fictional text example"
    photo = get_photo(st.session_state)
    photo_column, input_column = st.columns([1, 2.3], gap="large")
    with photo_column:
        if demo:
            st.info("Fictional text example — not your data. It does not use or change your selected personal photo.")
        else:
            render_photo_panel(st.session_state.laptop_camera, consented=face_sdk_metrics_opt_in, key="analysis_photo")
    with input_column:
        with st.form("analysis_form"):
            revision = photo_revision(st.session_state)
            include_photo = False
            uploaded = None
            consent = False
            if not demo:
                include_photo = st.checkbox("Include selected photo in analysis",
                    value=photo is not None and face_sdk_metrics_opt_in,
                    disabled=photo is None or not face_sdk_metrics_opt_in,
                    key=f"analysis_include_photo_{revision}_{face_sdk_metrics_opt_in}")
                if photo and not face_sdk_metrics_opt_in:
                    st.caption("Your photo stays selected. Face analysis is off; text and your optional rating can still be analyzed.")
                with st.expander("Optional video"):
                    uploaded = st.file_uploader("Short video (optional)", type=["mp4", "mov", "avi", "webm"],
                                                disabled=not face_sdk_metrics_opt_in, key="analysis_video")
                    st.caption("One person · up to 30 seconds · up to 40 MB. A supplied video is used instead of the selected photo for this analysis.")
                consent = st.checkbox("This is my image/video, or I have permission to analyze it.",
                                      wrap=True, key=f"analysis_media_permission_{revision}")
            st.subheader("Words")
            text_value = st.text_area("Describe what is happening or how you feel (English)",
                                     value=DEMO_TEXT if demo else "", height=155, max_chars=4000, key=f"text_{choice}")
            st.caption("Use at least 8 words. The model was trained on English Reddit passages; short messages may be unreliable.")
            include_rating = st.checkbox("Include a self-reported stress rating", value=False, key=f"include_{choice}")
            rating = st.slider("How stressed do you feel right now?", 0, 10, 5, key=f"rating_{choice}")
            st.caption("0 = none · 10 = very high. This is an informal personal rating, not a clinical questionnaire.")
            submitted = st.form_submit_button("Analyze example" if demo else "Analyze my inputs",
                                              type="primary", width="stretch")

    if submitted:
        st.session_state.pop("analysis", None)
        expected_revision = photo_revision(st.session_state)
        selected = get_photo(st.session_state)
        media = None
        filename, media_source = "", None
        if not demo:
            if uploaded is not None:
                media, filename, media_source = uploaded.getvalue(), uploaded.name, "video"
            elif include_photo and selected is not None:
                media, filename, media_source = selected.data, "selected-photo.png", "selected_photo"
        if media is not None and not face_sdk_metrics_opt_in:
            st.error("Face analysis is off. Review camera privacy in Live camera, or analyze text and your rating only.")
        elif media is not None and not consent:
            st.error("Please confirm permission for the image or video, or remove it from this analysis.")
        elif not media and not text_value.strip() and not include_rating:
            st.warning("Add text, a photo/video, or your own rating first.")
        else:
            with st.spinner("Running the local models…"):
                text_result = analyze_text(text_value) if text_value.strip() else None
                face_result = None
                if media:
                    extension = Path(filename).suffix.lower()
                    face_result = (analyze_video(media, extension) if media_source == "video" else analyze_image(media))
                own_rating = rating if include_rating else None
                committed = commit_analysis(st.session_state, {
                    "text": text_result, "face": face_result, "self_report": own_rating,
                    "summary": build_summary(text_result, face_result, own_rating),
                    "overview": analysis_overview(text_result, face_result, own_rating),
                    "media_source": media_source, "example": demo,
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                }, expected_revision=expected_revision)
                if not committed:
                    st.info("The selected photo changed while analysis ran. Analyze the current choice when ready.")

    with input_column:
        result = st.session_state.get("analysis")
        if result and not result.get("example") and (
            result.get("photo_revision", 0) != photo_revision(st.session_state)
            or ("photo_revision" not in result and result.get("face") is not None)
        ):
            st.session_state.pop("analysis", None)
            result = None
        if result:
            st.divider()
            st.subheader("Example results" if result["example"] else "Your results")
            if result["example"]:
                st.caption("Fictional text/rating example only; no personal or sample photo was analyzed.")
            tx, face = result["text"], result["face"]
            inputs = (["text"] if tx else []) + (["your rating"] if result["self_report"] is not None else [])
            if result.get("photo"):
                inputs.append("uploaded photo" if result["photo"]["source"] == "upload" else "camera still")
            elif result.get("media_source") == "video":
                inputs.append("video")
            when = datetime.fromisoformat(result["created_utc"]).astimezone(timezone.utc)
            st.caption(f"Analyzed {when.strftime('%d %b, %H:%M UTC')} · {', '.join(inputs) or 'no usable input'}")
            st.write(analysis_overview(tx, face, result["self_report"]))
            facol, txcol = st.columns(2, gap="large")
            with facol:
                st.subheader("Facial measurements")
                if face and face.get("status") == "ok":
                    st.image(face["annotated_image"], caption="Detected landmark positions", width=270)
                    groups = feature_groups(face["features"])
                    st.bar_chart(pd.DataFrame({"Coefficient": groups}), horizontal=True, color="#087E8B", height=250)
                    st.caption("Average left/right coefficients; 0–1. These are not emotion labels, stress percentages, or certified FACS codes.")
                    if face.get("timeline"):
                        render_feature_trend(face["timeline"], height=260)
                        st.caption("Time in seconds. Gaps mark missing measurements; lines do not bridge them.")
                    for message in face.get("warnings", []):
                        st.caption(message)
                elif face:
                    st.warning(face.get("message", "Face analysis is unavailable."))
                else:
                    st.info("No photo or video was supplied.")
            with txcol:
                st.subheader("Language patterns")
                if tx:
                    if tx.get("status") == "ok":
                        st.write("**" + ("Stress-related language" if tx["label"] == "stress" else "Less stress-related language") + "**")
                        st.caption("This describes wording, not your stress level.")
                    else:
                        st.warning(tx.get("explanation") or tx.get("message") or "Text could not be analyzed.")
                else:
                    st.info("No text was supplied.")
                st.caption("Language patterns, self-reports and facial movement do not establish a hidden emotional state.")
            with st.expander("More details · this result", expanded=False):
                st.caption(f"Analysis time (UTC): {result['created_utc']}. Results reflect this Analyze action.")
                if result.get("photo"):
                    st.caption(f"Photo source: {result['photo']['source']}; selected at (UTC): {result['photo']['selected_at_utc']}.")
                elif result.get("media_source") == "video":
                    st.caption("This result uses the supplied video. Your selected still is retained separately.")
                elif not result["example"]:
                    st.caption("No photo or video was included in this analysis; your selected still, if any, is retained separately.")
                a, b, c = st.columns(3)
                with a:
                    if tx and tx.get("status") == "ok":
                        st.metric("Stress-language model score", f"{tx['stress_probability']:.2f}")
                        st.caption("0–1 model output; uncalibrated. Not your probability or level of stress.")
                    else:
                        st.metric("Stress-language model", "No estimate")
                with b:
                    st.metric("Face frames measured", f"{face.get('face_frames', 0)} / {face.get('frames_requested', face.get('frames_analyzed', 0))}" if face else "Not provided")
                    if face and face.get("mode") == "video":
                        st.caption(f"{face.get('frames_analyzed', 0)} scheduled samples decoded; {face.get('decode_failures', 0)} could not be read.")
                    st.caption("Measures visible features, not psychological stress.")
                with c:
                    st.metric("Self-reported stress", f"{result['self_report']} / 10" if result['self_report'] is not None else "Not provided")
                    st.caption("Your own optional rating, kept separate from model output.")
                st.write(result["summary"])
                if tx:
                    st.write(tx.get("explanation", ""))
                    for message in tx.get("warnings", []):
                        st.caption(message)
                if tx and tx.get("top_terms"):
                    terms = tx["top_terms"]
                    st.caption("Words/phrases influencing this model result")
                    st.dataframe(pd.DataFrame(terms) if isinstance(terms[0], dict) else pd.DataFrame({"Term": terms}),
                                 hide_index=True, width="stretch")
                st.markdown("[Read the facial-stress pilot study](https://pmc.ncbi.nlm.nih.gov/articles/PMC10422124/)")
                report = {**result, "face": serializable_result(face),
                          "research_sources": [{"title": s["title"], "url": s["url"]} for s in SOURCES]}
                st.download_button("Download this result (JSON)", json.dumps(report, indent=2),
                                   "stresslens-result.json", "application/json")
                st.caption("Derived results and selection/analysis times only; no raw photo, original media or full input text.")
            if st.button("Clear analysis"):
                st.session_state.pop("analysis", None)
                st.rerun()
    st.caption("Analysis runs locally. Photo help explains storage and timing; source links open when you choose them.")

with research_tab:
    st.subheader("Evidence you can inspect")
    st.write(f"Search {len(SOURCES)} curated research notes and official references. This searches our notes; it does not read full books or generate new scientific claims.")
    with st.popover("How to read facial signals"):
        st.markdown("**Structure → movement → interpretation**")
        st.write("Structure is the underlying face shape. Movement is a change in the brows, eyelids or mouth. Interpretation asks what might explain it and needs context beyond the face.")
        st.markdown("Facial tissues change with aging at different rates between people. This app does not estimate age or treat permanent features as a current stress signal. [Anatomy review](https://pubmed.ncbi.nlm.nih.gov/27248022/)")
        st.markdown("[FACS describes visible movement](https://www.paulekman.com/facial-action-coding-system/). MediaPipe blendshapes are model estimates, not certified FACS codes. [Emotion-review authors](https://affective-science.org/wp-content/uploads/2024/04/barrett-et-al-2019-emotional-expressions-reconsidered-challenges-to-inferring-emotion-from-human-facial-movements.pdf) explain why facial movements alone do not reliably identify an inner emotional state.")
        st.write("Video shows change over time; a photo cannot show blink frequency. Pulse, breathing and cortisol are not measured here. A captured expression is a comparison reference, not proof of calmness.")
    query = st.text_input("Search the evidence", placeholder="Try: smiling, facial stress, video, or text dataset")
    sources = search_evidence(query, len(SOURCES)) if query.strip() else SOURCES
    if not sources:
        st.info("No matching note. Try a different term; the library is deliberately small.")
    for source in sources:
        render_source(source)

with model_tab:
    st.subheader("What runs under the hood")
    st.dataframe(pd.DataFrame([
        {"Library": "Streamlit", "Job": "Builds the browser interface from Python."},
        {"Library": "MediaPipe", "Job": "Runs Google's trained face-landmark and blendshape models locally."},
        {"Library": "OpenCV + threading", "Job": "Reads the laptop camera continuously while the interface updates."},
        {"Library": "OpenCV + Pillow", "Job": "Decode videos/photos and draw landmark previews."},
        {"Library": "scikit-learn", "Job": "Converts text to TF-IDF features and classifies language with logistic regression."},
        {"Library": "PyTorch + Transformers", "Job": "Runs a local Qwen language model to select wording from supplied alternatives."},
        {"Library": "pandas", "Job": "Organizes measurements, evaluation data and charts."},
        {"Library": "langdetect", "Job": "Screens for unsupported languages; imperfect on short text."},
        {"Library": "pytest", "Job": "Checks inference, invalid inputs, evidence logic and app behavior."},
    ]), hide_index=True, width="stretch")
    st.write("Live insights connect measured facial changes with curated research. Qwen2.5-0.5B selects among sentences assembled from the listed alternatives, locally in a separate worker. It does not decide which cause is true. Source notes appear when the model is unavailable or a result fails the checks. The upload summary remains deterministic. No API key is needed.")
    st.subheader("Text-model evaluation")
    metric_path = ROOT / "models" / "text_model_metrics.json"
    if metric_path.exists():
        try:
            metrics = json.loads(metric_path.read_text(encoding="utf-8"))
            if not isinstance(metrics, dict) or not isinstance(metrics.get("evaluation"), dict):
                raise ValueError("Evaluation metadata must contain an evaluation object.")
            evaluation = metrics["evaluation"]
            for key in ("accuracy", "macro_f1"):
                value = evaluation[key]
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not 0 <= value <= 1):
                    raise ValueError("Evaluation scores must be finite numbers between zero and one.")
            if type(evaluation["test_rows"]) is not int or evaluation["test_rows"] <= 0:
                raise ValueError("Test passage count must be a positive integer.")
            acc, f1, count = st.columns(3)
            acc.metric("Held-out accuracy", f"{evaluation['accuracy']:.1%}")
            f1.metric("Macro F1", f"{evaluation['macro_f1']:.3f}")
            count.metric("Test passages", str(evaluation["test_rows"]))
            st.json(metrics, expanded=False)
        except (OSError, ValueError, TypeError, KeyError):
            st.warning("The evaluation file is invalid or could not be read. Restore the verified model files or re-run scripts/train_text_model.py.")
    else:
        st.warning("Evaluation file unavailable. Run scripts/train_text_model.py.")
    st.write("This is an English text baseline evaluated on Dreaddit labels. It is not a validated facial or combined stress detector. Testing a different population needs new data and an independent evaluation.")
    st.subheader("Open the code in VS Code")
    st.code("app.py                    # interface\nstresslens/live.py         # continuous camera processing\nstresslens/live_ui.py      # live camera screen\nstresslens/insights.py     # sourced research connections\nstresslens/explainer.py    # local language-model summaries\nstresslens/face.py         # upload measurements\nstresslens/text_model.py   # language inference\nstresslens/evidence.py     # evidence notes\nscripts/train_text_model.py # reproduce training\ntests/                    # automated checks", language="text")
    st.caption("Press F5 in the project folder to run the app, or use START_STRESSLENS.cmd.")

with work_tab:
    st.button("Explore a fictional week", on_click=set_demo_mode, args=(True,), key="fictional_enter")
    render_wellbeing(ensure_report_controller(), summarize=summarize_checkins)
    with st.expander("What this shows · what has been checked"):
        st.write("Your work clock counts active time. Check-ins record only answers you choose to supply; "
                 "patterns count those answers by UTC day, keeping missing choices separate.")
        st.write("Software checks cover work controls, explicit saves, export behavior and storage choices. "
                 "They do not validate stress prediction or physical-camera performance. "
                 "The fictional week is a separate, view-only example.")
