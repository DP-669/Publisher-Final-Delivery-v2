"""
Publisher Final Delivery App v2
- Gemini 2.5 Pro: audio analysis (Tab 01)
- Claude Sonnet: all writing (Tabs 02-06)
- Dropbox: cloud folder integration
- Manual Refinement: fix any existing copy inline
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

# ── Custom Styling ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
    }
    .stApp { background-color: #0f0f0f; color: #e8e8e8; }
    .block-container { padding: 2rem 2.5rem; }

    h1, h2, h3 { font-family: 'DM Mono', monospace; letter-spacing: -0.02em; }
    h1 { font-size: 1.4rem; color: #ff3c3c; border-bottom: 1px solid #2a2a2a; padding-bottom: 0.75rem; margin-bottom: 1.5rem; }
    h2, h3 { font-size: 1rem; color: #e8e8e8; margin-bottom: 0.75rem; }

    .stButton > button {
        background-color: #1a1a1a;
        color: #e8e8e8;
        border: 1px solid #333;
        border-radius: 4px;
        font-family: 'DM Mono', monospace;
        font-size: 0.8rem;
        letter-spacing: 0.05em;
        padding: 0.5rem 1.2rem;
        transition: all 0.15s ease;
    }
    .stButton > button:hover {
        background-color: #ff3c3c;
        border-color: #ff3c3c;
        color: #fff;
    }
    .stButton > button[kind="primary"] {
        background-color: #ff3c3c;
        border-color: #ff3c3c;
        color: #fff;
    }

    .stTextArea textarea, .stTextInput input {
        background-color: #1a1a1a;
        color: #e8e8e8;
        border: 1px solid #2a2a2a;
        border-radius: 4px;
        font-family: 'DM Mono', monospace;
        font-size: 0.82rem;
    }
    .stTextArea textarea:focus, .stTextInput input:focus {
        border-color: #ff3c3c;
        box-shadow: none;
    }

    .stSelectbox > div > div {
        background-color: #1a1a1a;
        border: 1px solid #2a2a2a;
        color: #e8e8e8;
    }

    .stDataFrame { border: 1px solid #2a2a2a; }

    .stSidebar { background-color: #0a0a0a; border-right: 1px solid #1e1e1e; }
    .stSidebar .stRadio label { font-family: 'DM Mono', monospace; font-size: 0.78rem; color: #888; }
    .stSidebar .stRadio label:hover { color: #ff3c3c; }

    .status-badge {
        display: inline-block;
        padding: 0.2rem 0.6rem;
        border-radius: 3px;
        font-family: 'DM Mono', monospace;
        font-size: 0.7rem;
        letter-spacing: 0.08em;
        font-weight: 500;
        margin-bottom: 1rem;
    }
    .badge-ok { background: #1a2e1a; color: #4caf50; border: 1px solid #2d4a2d; }
    .badge-warn { background: #2e1a1a; color: #ff3c3c; border: 1px solid #4a2d2d; }
    .badge-info { background: #1a1e2e; color: #5b8cff; border: 1px solid #2d354a; }

    .copy-success { color: #4caf50; font-family: 'DM Mono', monospace; font-size: 0.75rem; }
    .prompt-block {
        background: #141414;
        border: 1px solid #2a2a2a;
        border-left: 3px solid #ff3c3c;
        border-radius: 4px;
        padding: 1rem 1.2rem;
        font-family: 'DM Mono', monospace;
        font-size: 0.78rem;
        line-height: 1.6;
        color: #c8c8c8;
        margin-bottom: 1rem;
        white-space: pre-wrap;
    }
    .divider { border: none; border-top: 1px solid #1e1e1e; margin: 1.5rem 0; }
    .stExpander { border: 1px solid #1e1e1e; border-radius: 4px; }
    .stAlert { border-radius: 4px; }
</style>
""", unsafe_allow_html=True)

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
    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    # API Keys
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

    # Status badges
    gemini_status = "badge-ok" if gemini_api_key else "badge-warn"
    claude_status = "badge-ok" if claude_api_key else "badge-warn"
    dropbox_status = "badge-ok" if dropbox_token else "badge-info"
    st.markdown(f"""
        <div class='status-badge {gemini_status}'>GEMINI {'✓' if gemini_api_key else '✗'}</div>
        <div class='status-badge {claude_status}'>CLAUDE {'✓' if claude_api_key else '✗'}</div>
        <div class='status-badge {dropbox_status}'>DROPBOX {'✓' if dropbox_token else '—'}</div>
    """, unsafe_allow_html=True)

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    catalog = st.selectbox("Active Catalog", ["EPP", "redCola", "SSC"])

    # Logo
    logo_map = {
        "redCola": "redCola logo 200x2001934x751.jpg",
        "SSC": "SSC 200x200 8.27.08#U202fPM.jpg",
        "EPP": "EPP 200x200.jpg",
    }
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "01_VISUAL_REFERENCES", catalog, logo_map[catalog])
        if os.path.exists(logo_path):
            st.image(logo_path, use_container_width=True)
    except Exception:
        pass

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

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

    st.markdown('<hr class="divider">', unsafe_allow_html=True)

    if st.button("Reset Session", use_container_width=True):
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
    }})" style="background:#1a1a1a;color:#888;border:1px solid #333;border-radius:3px;
    padding:4px 12px;font-family:'DM Mono',monospace;font-size:0.72rem;cursor:pointer;
    letter-spacing:0.06em;margin-bottom:8px;">
        {label}
    </button>
    <span id="cb_{key}" style="display:none;color:#4caf50;font-family:'DM Mono',monospace;
    font-size:0.72rem;margin-left:8px;">Copied ✓</span>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB 00 · FLIGHT DECK
# ══════════════════════════════════════════════════════════════════════════════
if active_tab == tabs[0]:
    st.title("THE FLIGHT DECK")
    st.markdown("""
    **Never Guess. Always Reference.**

    This app uses two AI models for two distinct jobs:
    - **Gemini 2.5 Pro** — Audio analysis. It listens, extracts structure and sonic detail.
    - **Claude Sonnet** — All writing. Track descriptions, album copy, MailChimp intros, MidJourney prompts.

    **The flow:**
    """)
    flow = [
        ("01", "Ingest Audio", "Upload files or pull from Dropbox. Gemini analyses each track."),
        ("02", "Track Descriptions", "Claude refines raw Gemini output through the Council filter."),
        ("03", "Album Description", "Claude synthesises the album arc from all track descriptions."),
        ("04", "Album Name", "Claude generates tail-end title concepts for your selection."),
        ("05", "Cover Art Prompts", "Claude writes MidJourney v7 prompts with copy buttons."),
        ("06", "MailChimp Intro", "Claude writes the editorial memo for supervisors."),
        ("07", "Fix Existing Copy", "Paste any bad copy — Claude rewrites it through the Council."),
        ("08", "Export", "Clean Room validation → ZIP file."),
    ]
    for num, name, desc in flow:
        st.markdown(f"`{num}` **{name}** — {desc}")

    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.info("Start by configuring your API keys in the sidebar, then select your catalog.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 01 · INGEST AUDIO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[1]:
    st.title("01 · INGEST AUDIO")

    if not gemini_api_key:
        st.error("Gemini API key required for audio analysis. Add it in the sidebar.")
        st.stop()

    col_upload, col_dropbox = st.columns([1, 1])

    # ── Direct Upload ──────────────────────────────────────────────────────────
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

    # ── Dropbox Integration ────────────────────────────────────────────────────
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
                            file_ext = os.path.splitext(f["name"])[1]
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

    # ── Error display ──────────────────────────────────────────────────────────
    if st.session_state.ingestion_error:
        st.error(st.session_state.ingestion_error)
        if st.button("Dismiss"):
            st.session_state.ingestion_error = None
            st.rerun()

    # ── Data Editor ───────────────────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.subheader("Track Data")

    if st.session_state.app_data["tracks"]:
        df = pd.DataFrame(st.session_state.app_data["tracks"])
        edited_df = st.data_editor(df, use_container_width=True, key="editor_tab1", num_rows="dynamic")
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

        st.markdown('<hr class="divider">', unsafe_allow_html=True)
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
            df, use_container_width=True, key="editor_tab2",
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
        st.subheader("Tail-End Sampling")
        st.write("5 concepts from the 0.01-0.09 probability range. No clichés allowed through.")
        if st.button("Generate Name Concepts", type="primary"):
            with st.spinner("Sampling the tails..."):
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
        st.write("4 prompts. Different framing, texture, and light source each. Copy directly into MidJourney.")

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

                result = st.session_state.engine.generate_cover_art_prompts(
                    st.session_state.app_data["album_name"],
                    st.session_state.app_data["album_description"],
                    catalog, selected_refs, claude_api_key
                )
                st.session_state.app_data["cover_art"] = result
            st.rerun()

        st.markdown('<hr class="divider">', unsafe_allow_html=True)
        st.caption("ℹ️ Replace `--sref [URL]` placeholders with actual reference image URLs from your 01_VISUAL_REFERENCES folder before using in MidJourney.")

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
            # Individual copy buttons per prompt
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
                result = st.session_state.engine.generate_mailchimp_intro(
                    st.session_state.app_data["album_name"],
                    st.session_state.app_data["album_description"],
                    catalog, claude_api_key,
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
# TAB 07 · FIX EXISTING COPY (Manual Refinement)
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab == tabs[7]:
    st.title("07 · FIX EXISTING COPY")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    st.write("Paste any copy that isn't working — over-hyped, sales-y, wrong for the catalog. Claude rewrites it through the full Council filter.")

    col_input, col_output = st.columns([1, 1])

    with col_input:
        content_type = st.selectbox(
            "Content type",
            ["Track Description", "Album Description", "MailChimp Intro", "Album Name", "Other"],
        )
        bad_copy = st.text_area("Paste the copy here", height=250, placeholder="Paste the text that needs fixing...")
        if st.button("Run Council Filter", type="primary", disabled=not bad_copy):
            with st.spinner("Council reviewing..."):
                st.session_state["refined_copy"] = st.session_state.engine.manual_refinement(
                    bad_copy, content_type, catalog, claude_api_key
                )

    with col_output:
        st.subheader("Refined Output")
        if "refined_copy" in st.session_state and st.session_state["refined_copy"]:
            result = st.session_state["refined_copy"]
            st.markdown(f'<div class="prompt-block">{result}</div>', unsafe_allow_html=True)
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

    passed, errors = st.session_state.engine.validate_data(st.session_state.app_data)

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
            use_container_width=True,
        )

        # Optional Dropbox upload
        if dropbox_token:
            st.markdown('<hr class="divider">', unsafe_allow_html=True)
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

    # ── Data summary ───────────────────────────────────────────────────────────
    st.markdown('<hr class="divider">', unsafe_allow_html=True)
    st.subheader("Session Summary")
    data = st.session_state.app_data
    cols = st.columns(4)
    cols[0].metric("Tracks", len(data.get("tracks", [])))
    cols[1].metric("Album Description", "✓" if data.get("album_description") else "—")
    cols[2].metric("MailChimp Intro", "✓" if data.get("mailchimp_intro") else "—")
    cols[3].metric("Cover Art Prompts", "✓" if data.get("cover_art") else "—")
