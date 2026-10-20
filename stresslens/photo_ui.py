"""Explicit still selection shared by existing live and personal-input views."""
import streamlit as st

from stresslens.personal_photo import capture_selection, choose_photo, get_photo, photo_revision, remove_photo


def _upload_photo(widget_key, expected_revision):
    uploaded = st.session_state.get(widget_key)
    if uploaded is None:
        return  # Empty uploader is not an implicit Remove.
    try:
        changed = choose_photo(st.session_state, uploaded.getvalue(), source="upload",
                               expected_revision=expected_revision)
    except ValueError as exc:
        st.session_state.personal_photo_notice = ("error", str(exc))
    else:
        if changed:
            st.session_state.personal_photo_notice = ("success", "Photo selected. Analyze again to compute a result for this choice.")


def render_photo_panel(camera, *, consented, key):
    photo = get_photo(st.session_state)
    with st.container(border=True):
        st.subheader("Your selected photo")
        if photo is None:
            st.caption("No photo selected. Upload a photo, or explicitly start the camera and then capture one.")
        else:
            st.image(photo.data, width="stretch")
            source = "Selected camera still" if photo.source == "camera" else "Uploaded photo"
            st.caption(f"{source} · {photo.selected_at.strftime('%d %b, %H:%M UTC')}")
        label = "Retake photo" if photo else "Capture photo"
        ready = consented and camera.running and not getattr(camera, "stopping", False)
        if st.button(label, disabled=not ready, key=key + "_capture", width="stretch"):
            try:
                capture_selection(st.session_state, camera, consented=consented)
            except (ValueError, RuntimeError) as exc:
                st.session_state.personal_photo_notice = ("error", str(exc))
            else:
                st.session_state.personal_photo_notice = ("success", "Camera still selected. Analyze again for this choice.")
                st.rerun()
        revision = photo_revision(st.session_state)
        upload_key = f"{key}_upload_{revision}"
        st.file_uploader("Upload another photo" if photo else "Upload a photo", type=["jpg", "jpeg", "png", "webp"],
                         key=upload_key, on_change=_upload_photo, args=(upload_key, revision))
        if st.button("Remove photo", disabled=photo is None, key=key + "_remove", width="stretch"):
            remove_photo(st.session_state)
            st.session_state.personal_photo_notice = ("success", "Photo removed; its current analysis was cleared.")
            st.rerun()
        if st.session_state.get("personal_photo_notice"):
            kind, notice = st.session_state.personal_photo_notice
            getattr(st, kind)(notice)
        st.caption("Kept for this app session; replace or remove anytime.")
        with st.expander("Photo help", expanded=False):
            if photo:
                st.caption(f"Selection time (UTC): {photo.selected_at.isoformat()}. This is a selected still, not the live feed.")
                if photo.source == "upload":
                    st.caption("The original photo capture time is unknown; upload time is not capture time.")
            st.caption("Camera-off and navigation keep this choice; there is no daily cutoff. Closing/reloading the app session or losing the process can lose it.")
            st.caption("No automatic disk save, external upload or photo export. Selecting a photo does not enable face features. Retake needs an already-started, consented camera.")
