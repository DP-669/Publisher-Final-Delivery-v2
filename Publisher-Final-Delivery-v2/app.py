"""
Publisher Final Delivery App v2
- Gemini 3.1 Pro: audio analysis (Tab 01)
- Claude Sonnet: all writing (Tabs 02-06)
- Dropbox: cloud folder integration
- Manual Refinement: fix any existing copy inline
- Light theme: clean Streamlit default
"""
import streamlit as st
import pandas as pd
import os
import random
from engine import IngestionEngine

st.set_page_config(
    page_title="Publisher Final Delivery",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Engine Init ────────────────────────────────────────────────────────────────
if "engine" not in st.session_state:
    st.session_state.engine = IngestionEngine()

if "app_data" not in st.session_state:
    st.session_state.app_data = {
        "tracks": [],
        "album_description": "",
        "album_name": "",
        "cover_art": "",
        "mailchimp_intro": "",
    }

if "ingestion_error" not in st.session_state:
    st.session_state.ingestion_error = None

if "dropbox_files" not in st.session_state:
    st.session_state.dropbox_files = []

# ── Sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### PUBLISHER FINAL DELIVERY")
    st.divider()

    gemini_api_key = st.secrets.get("GEMINI_API_KEY", None) or st.text_input(
        "Gemini API Key", type="password", key="gemini_key_input",
        placeholder="For audio analysis (Tab 01)"
    )
    claude_api_key = st.secrets.get("ANTHROPIC_API_KEY", None) or st.text_input(
        "Claude API Key", type="password", key="claude_key_input",
        placeholder="For all writing (Tabs 02-06)"
    )
    dropbox_token = st.secrets.get("DROPBOX_TOKEN", None) or st.text_input(
        "Dropbox Access Token", type="password", key="dropbox_key_input",
        placeholder="Optional — for cloud folder"
    )

    st.divider()

    col1, col2, col3 = st.columns(3)
    col1.markdown(f"**Gemini** {'✅' if gemini_api_key else '❌'}")
    col2.markdown(f"**Claude** {'✅' if claude_api_key else '❌'}")
    col3.markdown(f"**Dropbox** {'✅' if dropbox_token else '—'}")

    st.divider()

    catalog = st.selectbox("Active Catalog", ["EPP", "redCola", "SSC"])

    logo_map = {
        "redCola": "redCola logo 200x2001934x751.jpg",
        "SSC": "SSC 200x200 8.27.08#U202fPM.jpg",
        "EPP": "EPP 200x200.jpg",
    }
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "01_VISUAL_REFERENCES", catalog, logo_map[catalog])
        if os.path.exists(logo_path):
            st.image(logo_path, width=200)
    except Exception:
        pass

    st.divider()

    tabs = [
        "00 · Flight Deck",
        "01 · Ingest Audio",
        "02 · Track Descriptions",
        "03 · Album Description",
        "04 · Album Name",
        "05 · Cover Art Prompts",
        "06 · MailChimp Intro",
        "07 · Fix Existing Copy",
        "08 · Export",
    ]
    active_tab = st.radio("Navigate", tabs, label_visibility="collapsed")

    st.divider()

    if st.button("Reset Session"):
        st.session_state.app_data = {
            "tracks": [], "album_description": "",
            "album_name": "", "cover_art": "", "mailchimp_intro": "",
        }
        st.session_state.dropbox_files = []
        st.success("Session cleared.")


# ── Helper: copy button ────────────────────────────────────────────────────────
def copy_button(text: str, key: str, label: str = "Copy to Clipboard"):
    escaped = text.replace("`", "\\`").replace("\\", "\\\\")
    st.markdown(f"""
    <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>{{
        document.getElementById('cb_{key}').style.display='inline';
        setTimeout(()=>document.getElementById('cb_{key}').style.display='none', 2000);
    }})" style="cursor:pointer;padding:4px 12px;font-size:0.8rem;margin-bottom:8px;">
        {label}
    </button>
    <span id="cb_{key}" style="display:none;color:green;font-size:0.8rem;margin-left:8px;">Copied ✓</span>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 00 · FLIGHT DECK
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == tabs[0]:
    st.title("THE FLIGHT DECK")
    st.markdown("""
    **Never Guess. Always Reference.**

    Two AI models. Two distinct jobs:
    - **Gemini 3.1 Pro** — Audio analysis. Listens, extracts structure and sonic detail.
    - **Claude Sonnet** — All writing. Track descriptions, album copy, MailChimp intros, MidJourney prompts.
    """)

    st.subheader("The Flow")
    flow = [
        ("01", "Ingest Audio", "Upload files or pull from Dropbox. Gemini analyses each track."),
        ("02", "Track Descriptions", "Claude refines raw Gemini output through the Council filter."),
        ("03", "Album Description", "Claude synthesises the album arc from all track descriptions."),
        ("04", "Album Name", "Claude generates original title concepts for your selection."),
        ("05", "Cover Art Prompts", "Claude writes MidJourney v7 prompts with copy buttons."),
        ("06", "MailChimp Intro", "Claude writes the editorial memo for supervisors."),
        ("07", "Fix Existing Copy", "Paste any bad copy — Claude rewrites it through the Council."),
        ("08", "Export", "Clean Room validation → ZIP file."),
    ]
    for num, name, desc in flow:
        st.markdown(f"`{num}` **{name}** — {desc}")

    st.divider()
    st.info("Configure API keys in the sidebar, then select your catalog to begin.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 01 · INGEST AUDIO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[1]:
    st.title("01 · INGEST AUDIO")

    if not gemini_api_key:
        st.error("Gemini API key required for audio analysis. Add it in the sidebar.")
        st.stop()

    col_upload, col_dropbox = st.columns([1, 1])

    with col_upload:
        st.subheader("Upload Files")
        uploaded_files = st.file_uploader(
            "Drag audio files here", type=["mp3", "wav", "aiff", "flac"],
            accept_multiple_files=True, label_visibility="collapsed"
        )

        @st.dialog("Confirm Analysis")
        def run_analysis_dialog():
            st.write(f"Analysing {len(uploaded_files)} file(s) for **{catalog}**. Confirm?")
            if st.button("Run Analysis"):
                progress = st.progress(0)
                for idx, uploaded_file in enumerate(uploaded_files):
                    clean_title = os.path.splitext(uploaded_file.name)[0]
                    file_ext = os.path.splitext(uploaded_file.name)[1]
                    safe_path = f"{clean_title}{file_ext}"
                    with open(safe_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    try:
                        metadata = st.session_state.engine.analyze_audio_file(
                            safe_path, clean_title, catalog, gemini_api_key
                        )
                        if metadata:
                            existing_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                            if clean_title not in existing_titles:
                                st.session_state.app_data["tracks"].append({
                                    "Title": clean_title,
                                    "Keywords": metadata.get("Keywords", ""),
                                    "Track Description": metadata.get("Description", ""),
                                })
                    except Exception as e:
                        import traceback
                        st.session_state.ingestion_error = f"Failed: {clean_title}\n{traceback.format_exc()}"
                    finally:
                        if os.path.exists(safe_path):
                            os.remove(safe_path)
                    progress.progress((idx + 1) / len(uploaded_files))
                st.success("Analysis complete.")
                st.rerun()

        if st.button("Analyse with Gemini", disabled=not uploaded_files):
            run_analysis_dialog()

    with col_dropbox:
        st.subheader("From Dropbox")
        if not dropbox_token:
            st.info("Add your Dropbox token in the sidebar to enable cloud folder access.")
        else:
            dropbox_folder = st.text_input(
                "Dropbox folder path", value="", placeholder="/Music/New Album",
                help="Leave empty for root folder"
            )
            col_list, col_analyse = st.columns([1, 1])
            with col_list:
                if st.button("List Files"):
                    with st.spinner("Connecting to Dropbox..."):
                        try:
                            files = st.session_state.engine.list_dropbox_audio_files(
                                dropbox_token, dropbox_folder
                            )
                            st.session_state.dropbox_files = files
                            if not files:
                                st.warning("No audio files found in that folder.")
                        except Exception as e:
                            st.error(str(e))

            if st.session_state.dropbox_files:
                st.write(f"**{len(st.session_state.dropbox_files)} files found:**")
                selected = []
                for f in st.session_state.dropbox_files:
                    if st.checkbox(f["name"], key=f"dbx_{f['path']}"):
                        selected.append(f)

                with col_analyse:
                    if st.button("Analyse Selected", disabled=not selected):
                        progress = st.progress(0)
                        for idx, f in enumerate(selected):
                            clean_title = os.path.splitext(f["name"])[0]
                            local_path = f"/tmp/{f['name']}"
                            try:
                                st.session_state.engine.download_from_dropbox(
                                    dropbox_token, f["path"], local_path
                                )
                                metadata = st.session_state.engine.analyze_audio_file(
                                    local_path, clean_title, catalog, gemini_api_key
                                )
                                if metadata:
                                    existing_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                                    if clean_title not in existing_titles:
                                        st.session_state.app_data["tracks"].append({
                                            "Title": clean_title,
                                            "Keywords": metadata.get("Keywords", ""),
                                            "Track Description": metadata.get("Description", ""),
                                        })
                            except Exception as e:
                                st.error(f"Failed {f['name']}: {str(e)}")
                            finally:
                                if os.path.exists(local_path):
                                    os.remove(local_path)
                            progress.progress((idx + 1) / len(selected))
                        st.success("Dropbox analysis complete.")
                        st.rerun()

    if st.session_state.ingestion_error:
        st.error(st.session_state.ingestion_error)
        if st.button("Dismiss"):
            st.session_state.ingestion_error = None
            st.rerun()

    st.divider()
    st.subheader("Track Data")

    if st.session_state.app_data["tracks"]:
        df = pd.DataFrame(st.session_state.app_data["tracks"])
        edited_df = st.data_editor(df, key="editor_tab1", num_rows="dynamic")
        st.session_state.app_data["tracks"] = edited_df.to_dict("records")
        csv = edited_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Keywords CSV", csv, "Keywords.csv", "text/csv")
    else:
        st.info("No tracks ingested yet. Upload files or connect Dropbox above.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 02 · TRACK DESCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[2]:
    st.title("02 · TRACK DESCRIPTIONS")

    if not st.session_state.app_data["tracks"]:
        st.warning("Ingest tracks in Tab 01 first.")
        st.stop()

    if not claude_api_key:
        st.error("Claude API key required. Add it in the sidebar.")
        st.stop()

    col_action, col_editor = st.columns([1, 1])

    with col_action:
        st.subheader("Refine All Descriptions")
        st.write("Claude runs all raw Gemini descriptions through the Council filter.")
        if st.button("Run Council Refinement", type="primary"):
            with st.spinner("Council working..."):
                updated = []
                prog = st.progress(0)
                tracks = st.session_state.app_data["tracks"]
                for idx, track in enumerate(tracks):
                    refined = st.session_state.engine.refine_track_description(
                        track["Title"],
                        track.get("Track Description", ""),
                        catalog,
                        claude_api_key,
                    )
                    track["Track Description"] = refined
                    updated.append(track)
                    prog.progress((idx + 1) / len(tracks))
                st.session_state.app_data["tracks"] = updated
            st.success("All descriptions refined.")
            st.rerun()

        st.divider()
        st.subheader("Refine Single Track")
        track_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
        selected_track = st.selectbox("Select track", track_titles)
        if st.button("Refine Selected"):
            with st.spinner("Refining..."):
                track = next(t for t in st.session_state.app_data["tracks"] if t["Title"] == selected_track)
                refined = st.session_state.engine.refine_track_description(
                    track["Title"], track.get("Track Description", ""), catalog, claude_api_key
                )
                track["Track Description"] = refined
            st.success(f"'{selected_track}' updated.")
            st.rerun()

    with col_editor:
        st.subheader("Edit & Export")
        df = pd.DataFrame(st.session_state.app_data["tracks"])
        edited_df = st.data_editor(
            df, key="editor_tab2",
            disabled=["Title", "Keywords"],
        )
        st.session_state.app_data["tracks"] = edited_df.to_dict("records")
        csv = edited_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download Descriptions CSV", csv, "Descriptions.csv", "text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 03 · ALBUM DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[3]:
    st.title("03 · ALBUM DESCRIPTION")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Synthesise from Track Descriptions")
        track_count = len(st.session_state.app_data["tracks"])
        if track_count == 0:
            st.warning("No tracks loaded. Complete Tab 01 first.")
        else:
            st.write(f"Synthesising from {track_count} track description(s).")
            if st.button("Generate Album Description", type="primary"):
                with st.spinner("Council synthesising..."):
                    descs = [t.get("Track Description", "") for t in st.session_state.app_data["tracks"]]
                    result = st.session_state.engine.generate_album_description(
                        descs, catalog, claude_api_key
                    )
                    st.session_state.app_data["album_description"] = result
                st.rerun()

    with col_output:
        st.subheader("Output")
        edited = st.text_area(
            "Album Description",
            value=st.session_state.app_data["album_description"],
            height=150,
            label_visibility="collapsed",
        )
        st.session_state.app_data["album_description"] = edited
        if edited:
            copy_button(edited, "album_desc")
            st.download_button(
                "Download TXT", edited.encode("utf-8"),
                "Album_Description.txt", "text/plain"
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 04 · ALBUM NAME
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[4]:
    st.title("04 · ALBUM NAME")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Generate Title Concepts")
        st.write("5 original concepts. No clichés allowed through.")
        if st.button("Generate Name Concepts", type="primary"):
            with st.spinner("Generating concepts..."):
                result = st.session_state.engine.generate_album_names(
                    st.session_state.app_data["album_description"], catalog, claude_api_key
                )
                st.session_state.app_data["album_name"] = result
            st.rerun()

    with col_output:
        st.subheader("Concepts")
        edited = st.text_area(
            "Album Name Concepts",
            value=st.session_state.app_data["album_name"],
            height=220,
            label_visibility="collapsed",
        )
        st.session_state.app_data["album_name"] = edited
        if edited:
            copy_button(edited, "album_name")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 05 · COVER ART PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[5]:
    st.title("05 · COVER ART PROMPTS")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Generate MidJourney v7 Prompts")
        st.write("4 prompts. Different framing, texture, and light source each.")

        if st.button("Generate Prompts", type="primary"):
            with st.spinner("Art Director working..."):
                refs = []
                cat_folder = (
                    st.session_state.engine.root_path / "01_VISUAL_REFERENCES" / catalog
                )
                if cat_folder.exists():
                    refs = [
                        f"https://placeholder.url/{f.name}"
                        for f in cat_folder.iterdir()
                        if f.is_file() and not f.name.startswith(".")
                    ]
                if not refs:
                    refs = ["https://dummy.url/ref1.jpg"] * 4
                selected_refs = random.choices(refs, k=4)

                track_descriptions = [
                    t.get("Track Description", "")
                    for t in st.session_state.app_data["tracks"]
                ]
                keywords = ", ".join([
                    t.get("Keywords", "")
                    for t in st.session_state.app_data["tracks"]
                    if t.get("Keywords")
                ])

                result = st.session_state.engine.generate_cover_art_prompts(
                    st.session_state.app_data["album_name"],
                    st.session_state.app_data["album_description"],
                    catalog,
                    selected_refs,
                    claude_api_key,
                    track_descriptions=track_descriptions,
                    keywords=keywords,
                )
                st.session_state.app_data["cover_art"] = result
            st.rerun()

        st.divider()
        st.caption("Replace `--sref [URL]` placeholders with actual reference image URLs before using in MidJourney.")

    with col_output:
        st.subheader("Prompts")
        edited = st.text_area(
            "MidJourney Prompts",
            value=st.session_state.app_data["cover_art"],
            height=400,
            label_visibility="collapsed",
        )
        st.session_state.app_data["cover_art"] = edited

        if edited:
            prompts = [p.strip() for p in edited.split("\n\n") if p.strip()]
            for i, p in enumerate(prompts):
                copy_button(p, f"prompt_{i}", f"Copy Prompt {i+1}")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 06 · MAILCHIMP INTRO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[6]:
    st.title("06 · MAILCHIMP INTRO")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Generate Editorial Memo")
        st.write("Identifies the editor's pain point first. No sales pitch. No 'proud to announce'.")
        if st.button("Write MailChimp Intro", type="primary"):
            with st.spinner("Copywriter drafting..."):
                track_descriptions = [
                    t.get("Track Description", "")
                    for t in st.session_state.app_data["tracks"]
                ]
                result = st.session_state.engine.generate_mailchimp_intro(
                    st.session_state.app_data["album_name"],
                    st.session_state.app_data["album_description"],
                    catalog,
                    claude_api_key,
                    track_descriptions=track_descriptions,
                )
                st.session_state.app_data["mailchimp_intro"] = result
            st.rerun()

    with col_output:
        st.subheader("Output")
        edited = st.text_area(
            "MailChimp Copy",
            value=st.session_state.app_data["mailchimp_intro"],
            height=200,
            label_visibility="collapsed",
        )
        st.session_state.app_data["mailchimp_intro"] = edited
        if edited:
            copy_button(edited, "mailchimp")
            st.download_button(
                "Download TXT", edited.encode("utf-8"),
                "MailChimp_Intro.txt", "text/plain"
            )


# ══════════════════════════════════════════════════════════════════════════════
# TAB 07 · FIX EXISTING COPY
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[7]:
    st.title("07 · FIX EXISTING COPY")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    st.write("Paste any copy that isn't working — over-hyped, wrong catalog language, too generic. Claude rewrites it through the full Council filter.")

    col_input, col_output = st.columns([1, 1])

    with col_input:
        content_type = st.selectbox(
            "Content type",
            ["Track Description", "Album Description", "MailChimp Intro", "Album Name", "Other"],
        )
        bad_copy = st.text_area(
            "Paste the copy here", height=250,
            placeholder="Paste the text that needs fixing..."
        )
        if st.button("Run Council Filter", type="primary", disabled=not bad_copy):
            with st.spinner("Council reviewing..."):
                st.session_state["refined_copy"] = st.session_state.engine.manual_refinement(
                    bad_copy, content_type, catalog, claude_api_key
                )

    with col_output:
        st.subheader("Refined Output")
        if "refined_copy" in st.session_state and st.session_state["refined_copy"]:
            result = st.session_state["refined_copy"]
            st.text_area("Refined", value=result, height=250, label_visibility="collapsed")
            copy_button(result, "manual_refine")

            st.markdown("**Apply this output to:**")
            apply_col1, apply_col2 = st.columns(2)
            with apply_col1:
                if st.button("→ Album Description"):
                    st.session_state.app_data["album_description"] = result
                    st.success("Applied.")
                if st.button("→ MailChimp Intro"):
                    st.session_state.app_data["mailchimp_intro"] = result
                    st.success("Applied.")
            with apply_col2:
                if st.button("→ Album Name"):
                    st.session_state.app_data["album_name"] = result
                    st.success("Applied.")
                if content_type == "Track Description":
                    track_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                    if track_titles:
                        apply_track = st.selectbox("Apply to track:", track_titles, key="apply_track")
                        if st.button("→ Apply to Track"):
                            for t in st.session_state.app_data["tracks"]:
                                if t["Title"] == apply_track:
                                    t["Track Description"] = result
                            st.success(f"Applied to '{apply_track}'.")
        else:
            st.info("Refined output will appear here.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 08 · EXPORT
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[8]:
    st.title("08 · EXPORT")

    st.subheader("Clean Room Validator")
    st.write("Checking data integrity before allowing export...")

    passed, errors = st.session_state.engine.validate_data(
        st.session_state.app_data, catalog
    )

    if not passed:
        st.error(f"{len(errors)} error(s) blocking export:")
        for msg in errors:
            st.warning(msg)
    else:
        st.success("Clean Room passed ✓ — all checks clear.")

        zip_buffer = st.session_state.engine.compile_final_package(st.session_state.app_data)

        st.download_button(
            label="Download Final Delivery ZIP",
            data=zip_buffer,
            file_name=f"{catalog}_Final_Delivery.zip",
            mime="application/zip",
            type="primary",
        )

        if dropbox_token:
            st.divider()
            st.subheader("Save to Dropbox")
            output_folder = st.text_input(
                "Dropbox output folder",
                value="/Publisher Output",
                help="Where to save the ZIP in your Dropbox"
            )
            album_name_safe = st.session_state.app_data.get("album_name", "album").split("\n")[0][:30].strip()
            dest_path = f"{output_folder}/{catalog}_{album_name_safe}_Final_Delivery.zip"

            if st.button("Upload ZIP to Dropbox"):
                with st.spinner("Uploading..."):
                    try:
                        import tempfile
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                            tmp.write(zip_buffer.read())
                            tmp_path = tmp.name
                        st.session_state.engine.upload_to_dropbox(
                            dropbox_token, tmp_path, dest_path
                        )
                        os.remove(tmp_path)
                        st.success(f"Uploaded to Dropbox: `{dest_path}`")
                    except Exception as e:
                        st.error(str(e))

    st.divider()
    st.subheader("Session Summary")
    data = st.session_state.app_data
    cols = st.columns(4)
    cols[0].metric("Tracks", len(data.get("tracks", [])))
    cols[1].metric("Album Description", "✓" if data.get("album_description") else "—")
    cols[2].metric("MailChimp Intro", "✓" if data.get("mailchimp_intro") else "—")
    cols[3].metric("Cover Art Prompts", "✓" if data.get("cover_art") else "—")
