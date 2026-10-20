"""Live camera page; UI refresh does not rebuild the face model."""
import pandas as pd
import streamlit as st

from stresslens.live import LaptopCamera, LiveFaceSession, live_feedback
from stresslens.insights import research_insights
from stresslens.explainer import LiveExplainer
from stresslens.charts import render_feature_trend
from stresslens.session_ui import ensure_report_controller, render_segment_options, render_report_panel
from stresslens.live_status import live_status
from stresslens.photo_ui import render_photo_panel


def render_live_camera():
    st.subheader("Watch your face live")
    st.caption("Explore facial movement and changes from your reference.")
    controller = ensure_report_controller()
    legacy_session = st.session_state.get("live_session")
    legacy_camera = st.session_state.get("laptop_camera")
    migrate_idle = (isinstance(legacy_session, LiveFaceSession) and legacy_session.report_workspace is None
                    and legacy_camera is not None and not legacy_camera.running
                    and getattr(legacy_camera, "release_confirmed", True))
    if legacy_session is None or migrate_idle:
        st.session_state.live_session = LiveFaceSession(clock=controller.clock, report_workspace=controller.workspace)
        st.session_state.laptop_camera = LaptopCamera(st.session_state.live_session, utc_clock=controller.camera_utc)
    session = st.session_state.live_session
    camera = st.session_state.laptop_camera
    if "live_explainer" not in st.session_state:
        st.session_state.live_explainer = LiveExplainer()
    explainer = st.session_state.live_explainer
    # Stop must remain above potentially long readings while a session runs.
    if camera.running:
        action_area = st.container(key="camera_actions")
        preview_area = st.container()
    else:
        preview_area = st.container()
        action_area = st.container(key="camera_actions")
    with action_area:
        privacy, start, stop = st.columns([1.3, 1, 1], gap="small")
        opted_in = st.session_state.get("face_sdk_metrics_opt_in", False)
        with privacy.popover("Face privacy" if opted_in else "Review camera privacy",
                             type="secondary" if opted_in else "primary", width="stretch"):
            st.markdown("**Before using face features**")
            st.write("Face images are processed on your laptop. Google's MediaPipe SDK sends usage and performance metrics, "
                     "app and general media metadata, and host system/version information to Google.")
            st.markdown("[Read Google's SDK notice](https://developers.google.com/edge/mediapipe/legal/tos)")
            face_sdk_metrics_opt_in = st.checkbox(
                "Enable face features and allow the MediaPipe SDK metrics described above to be sent to Google",
                value=False, key="face_sdk_metrics_opt_in",
            )
            st.caption("This does not start the camera. Close this panel to continue. Text analysis and sources remain available without opting in.")
            st.caption("Turning this off stops face processing; it cannot retract metrics already sent.")
    if not face_sdk_metrics_opt_in:
        explainer.reset()
        if camera.running and not getattr(camera, "stopping", False):
            camera.stop(reason="consent_revoked")
    released = getattr(camera, "release_confirmed", not camera.running)
    with st.expander("Camera options", expanded=False):
        index = st.selectbox("Camera", [0, 1, 2], disabled=camera.running or not released, key="report_camera_index",
                             format_func=lambda x: "Default camera" if x == 0 else f"Camera {x + 1}")
        auto_explain = st.checkbox("Summarize significant changes with the local language model", value=True)
        config = render_segment_options(disabled=camera.running or not released)
        st.caption("No video is recorded. The camera stops after 20 seconds without page updates.")
    if start.button("Start camera", type="primary" if face_sdk_metrics_opt_in else "secondary",
                    disabled=camera.running or not released or not face_sdk_metrics_opt_in, width="stretch") and face_sdk_metrics_opt_in:
        explainer.reset()
        try:
            camera.start(index, segment_config=config)
            controller.camera_started(session, config)
        except (ValueError, RuntimeError) as exc:
            st.error(f"Camera was not started: {exc}")
        else:
            st.rerun()
    if stop.button("Stop camera", disabled=not camera.running or getattr(camera, "stopping", False), width="stretch"):
        camera.stop()
        explainer.reset()
        st.rerun()

    active = camera.running
    with st.expander("Your comparison reference", expanded=active):
        ref, reset = st.columns(2)
        if ref.button("Capture reference · 8s", disabled=not active or not face_sdk_metrics_opt_in or getattr(camera, "stopping", False), width="stretch"):
            session.capture_reference()
        if reset.button("Clear reference", disabled=not face_sdk_metrics_opt_in or getattr(camera, "stopping", False), width="stretch"):
            session.clear_reference()
        st.caption("For a reference, keep one clear face in view with a comfortable, neutral expression.")

    @st.fragment(run_every=0.25 if active else None)
    def readings():
        if active and not camera.running:
            st.rerun()  # Restore controls after camera errors or the idle timeout.
        stopping = getattr(camera, "stopping", False)
        if stopping:
            snapshot = {"status": "stopping", "message": "Camera is stopping. Waiting for the device to finish.", "history": []}
        elif not face_sdk_metrics_opt_in:
            snapshot = {"status": "disabled", "message": "Face features are off. Choose Review camera privacy below to begin.", "history": []}
        else:
            snapshot = session.snapshot()
        preview, error = camera.preview()
        if not face_sdk_metrics_opt_in:
            preview = None
        report = controller.workspace.snapshot()
        last = report.segments[-1] if report.segments else None
        status = live_status(
            snapshot, running=camera.running, stopping=stopping,
            released=getattr(camera, "release_confirmed", not camera.running),
            consented=face_sdk_metrics_opt_in, error=error, last_reason=last.reason if last else None,
        )
        quiet = status.state in {"off", "stopping"}
        left, right = st.columns([1.65, 1], gap="large")
        with left:
            with st.container(border=True, key="camera_preview"):
                st.markdown("### " + status.title)
                st.info(status.message)
                if status.start_hint:
                    st.caption(status.start_hint)
                if status.freshness:
                    st.caption(status.freshness)
                if error:
                    st.error(error)
                if preview and not quiet:
                    st.image(preview, width="stretch")
                    st.caption("Latest received frame; see freshness above. No video is recorded.")
                if last:
                    st.caption("Latest finalized camera observation (UTC): "
                               f"{last.start_utc.isoformat()} to {last.end_utc.isoformat()}. "
                               f"Stop reason: {last.reason}. This is historical, not a current reading.")
                else:
                    st.caption("No finalized camera observations.")
                st.caption("Stored in this app session only; an app/process loss can lose unsaved data. "
                           "Download your report to keep a local copy; capture is never restored automatically.")
        with right:
            if quiet:
                st.markdown("### Your observations")
                st.caption("Self-reports and device readings remain separate in Your session report below. "
                           "An optional expression reference never establishes calmness.")
            elif status.current:
                fps, delay = st.columns(2)
                fps.metric("Measurement rate", f"{snapshot['measurement_fps']:.1f} /s")
                delay.metric("Model time", f"{snapshot.get('latency_ms', 0):.0f} ms")
                st.write(live_feedback(snapshot))
                df = pd.DataFrame({"Feature": list(snapshot["groups"]), "Coefficient": list(snapshot["groups"].values())})
                if snapshot.get("changes"):
                    df["Change from reference"] = [snapshot["changes"][k] for k in df["Feature"]]
                with st.expander("More details · live measurements", expanded=False):
                    st.dataframe(df, hide_index=True, width="stretch")
            if "reference_progress" in snapshot:
                st.progress(snapshot["reference_progress"], text="Capturing your reference…")
            if snapshot.get("reference_message"):
                st.caption(snapshot["reference_message"])
        if quiet:
            return
        history = snapshot.get("history", [])
        if history and any(row.get("Brow lowering") is not None for row in history):
            render_feature_trend(history)
            st.caption("Recent measured samples. Gaps mark missing measurements; lines do not bridge them.")
        if not status.current:
            return
        cards = research_insights(snapshot)
        st.subheader("Research-informed insights")
        if not cards:
            st.caption("Insights appear once one clear face is tracked. Reference capture temporarily pauses interpretation.")
        else:
            for card in cards:
                with st.container(border=True):
                    st.write("**" + card["title"] + "**")
                    st.write("**Observed:** " + card["observation"])
                    st.write("**Research connection:** " + card["research_connection"])
                    if card.get("alternatives"):
                        st.caption("Other explanations: " + "; ".join(card["alternatives"]) + ".")
                    st.caption(card["limitation"])
                    st.markdown(f"[{card['source_title']}]({card['source_url']})")
            if auto_explain:
                explainer.request(cards)
                explanation = explainer.result(cards)
                if explanation:
                    st.write("**Plain-English summary**")
                    st.write(explanation["text"])
                    if explanation["status"] == "working":
                        st.caption("The camera keeps running while the local summarizer works.")
                    elif explanation.get("mode") == "local_llm":
                        st.caption(f"Qwen2.5 selected wording from the listed alternatives locally in {explanation['elapsed_seconds']:.1f}s. It does not choose which cause is true. The observation and limits come from the source cards.")
                    else:
                        st.caption(explanation.get("message", "Showing checked research notes."))

    with preview_area:
        readings()

    @st.fragment(run_every=1 if active else None)
    def report_view():
        if active and not camera.running:
            st.rerun()
        if controller._active is not None and camera.running and not getattr(camera, "stopping", False):
            _, active_config, _, began = controller._active
            st.caption(f"Current observation: {min(active_config.deadline, max(0, controller.clock() - began)):.0f} seconds. "
                       "Optional start/end check-ins are below; they never delay camera release.")
        render_report_panel(controller, session, camera, explainer)

    photo_column, report_column = st.columns([1, 2.3], gap="large")
    with photo_column:
        render_photo_panel(camera, consented=face_sdk_metrics_opt_in, key="live_photo")
    with report_column:
        report_view()
    st.caption("Insights are tentative research analogies about measured facial changes. They do not establish a mental-health condition or an exact stress level.")
    st.caption("Processing stays on this laptop. No video is recorded. Only Capture photo/Retake selects a still, held in this app session until replacement/removal or session loss. Press Stop to release the camera; direct camera mode also stops after 20 seconds without page updates.")
    with st.expander("How the live system works"):
        st.write("Camera → MediaPipe → measured facial changes → curated research associations → optional local Qwen summary. The face model is reused while the camera runs. A separate worker selects source-bounded wording for a changed pattern at most every 15 seconds. Papers supply context and limitations; they do not turn a facial coefficient into an exact stress score.")
        st.markdown("[Local language model](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)")
    return face_sdk_metrics_opt_in
