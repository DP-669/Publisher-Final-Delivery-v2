"""
Publisher Final Delivery App v2
- Gemini 3.1 Pro: audio analysis (Tab 01) — 6 fields per track
- Claude Sonnet 5: all writing (Tabs 02-06) — Tab 02 synthesizes 6 fields into master description
- Dropbox Pipeline: paste a shared link → auto-crawl → auto-analyze → auto-synthesize → ntfy
- Manual Refinement: fix any existing copy inline
"""
import streamlit as st
import pandas as pd
import os
import re
import time
import random
from engine import IngestionEngine

try:
    from dropbox_pipeline import (
        CrawlResult, FileEntry, crawl_album_folder, detect_catalog_from_path,
        is_quality_checked, resolve_shared_link, make_batches,
        generate_alt_description, generate_cutdown_description, send_ntfy,
        is_quota_error,
    )
    PIPELINE_AVAILABLE = True
except ImportError:
    PIPELINE_AVAILABLE = False

try:
    from persistence import save_progress, list_sessions, delete_progress
    PERSISTENCE_AVAILABLE = True
except ImportError:
    PERSISTENCE_AVAILABLE = False

st.set_page_config(
    page_title="Publisher Final Delivery",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { max-width: 860px; padding: 2rem 2rem; }
    @media (max-width: 768px) { .block-container { max-width: 100%; padding: 1rem 0.75rem; } }
    .stSidebar .block-container { max-width: 100%; }
    .stDataFrame, .stDataEditor { width: 100% !important; }
    .stTextArea textarea { width: 100% !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; } }
    .mailchimp-output {
        white-space: pre-wrap; font-family: Georgia, serif; font-size: 1rem;
        line-height: 1.8; padding: 1.5rem; border: 1px solid #e0e0e0;
        border-radius: 6px; background: #fafafa; margin-bottom: 1rem;
    }
    .contamination-warn {
        background: #fff3cd; border: 1px solid #ffc107; border-left: 4px solid #ff6b35;
        border-radius: 4px; padding: 0.4rem 0.8rem; font-size: 0.8rem;
        margin-top: 0.3rem; margin-bottom: 0.5rem;
    }
    .mix-badge-full { background:#e3f2fd;color:#1565c0;border-radius:3px;padding:2px 8px;font-size:0.75rem;font-weight:600;margin-left:6px; }
    .mix-badge-sparse { background:#f3e5f5;color:#6a1b9a;border-radius:3px;padding:2px 8px;font-size:0.75rem;font-weight:600;margin-left:6px; }
    .mix-badge-sde { background:#e8f5e9;color:#2e7d32;border-radius:3px;padding:2px 8px;font-size:0.75rem;font-weight:600;margin-left:6px; }
    .mix-badge-alt { background:#fff8e1;color:#f57f17;border-radius:3px;padding:2px 8px;font-size:0.75rem;font-weight:600;margin-left:6px; }
    .next-button-container { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid #e0e0e0; }
    .gemini-source-field { background:#f8f9fa;border-left:3px solid #dee2e6;padding:0.5rem 0.75rem;margin-bottom:0.4rem;font-size:0.85rem;border-radius:0 4px 4px 0; }
    .gemini-source-label { font-size:0.7rem;font-weight:700;color:#6c757d;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:2px; }
    .pipeline-log { font-family:monospace;font-size:0.78rem;background:#f8f8f8;padding:0.75rem;border-radius:4px;max-height:200px;overflow-y:auto; }
</style>
""", unsafe_allow_html=True)

# ── Tab definitions ────────────────────────────────────────────────────────────
TABS = [
    "00 · Home",
    "01 · Ingest Audio",
    "02 · Track Descriptions",
    "03 · Album Description",
    "04 · Album Name",
    "05 · Cover Art Prompts",
    "06 · MailChimp Intro",
    "07 · Fix Existing Copy",
    "08 · Export",
]

# ── Engine Init ────────────────────────────────────────────────────────────────
if "engine" not in st.session_state:
    st.session_state.engine = IngestionEngine()

if "app_data" not in st.session_state:
    st.session_state.app_data = {
        "tracks": [], "album_description": "", "album_name": "",
        "album_name_selected": "", "cover_art": "", "mailchimp_intro": "",
        "catalog": "EPP",
    }

if "active_tab_index" not in st.session_state:
    st.session_state.active_tab_index = 0

if "ingestion_error" not in st.session_state:
    st.session_state.ingestion_error = None

if "dropbox_files" not in st.session_state:
    st.session_state.dropbox_files = []

if "track_history" not in st.session_state:
    st.session_state.track_history = {}

_PIPE_DEFAULT = {
    "status": "idle",        # idle | crawling | processing | synthesizing | done | error
    "shared_link": "",
    "album_path": "",
    "album_name": "",
    "catalog": "",
    "crawl_log": [],
    "queue": [],             # list of lists of FileEntry
    "processed_count": 0,
    "total_to_analyze": 0,
    "current_file": "",
    "log": [],
    "error": "",
    "heartbeat_count": 0,
    "dropbox_output_path": "",
}

if "pipeline" not in st.session_state:
    st.session_state.pipeline = dict(_PIPE_DEFAULT)


# ── Helpers ────────────────────────────────────────────────────────────────────
def go_to_tab(index: int):
    st.session_state.active_tab_index = index
    st.rerun()


def next_button(label_override: str = None):
    current = st.session_state.active_tab_index
    if current < len(TABS) - 1:
        next_name = TABS[current + 1]
        label = label_override or f"Next → {next_name}"
        st.markdown('<div class="next-button-container">', unsafe_allow_html=True)
        if st.button(label, type="primary", key=f"next_btn_{current}"):
            go_to_tab(current + 1)
        st.markdown('</div>', unsafe_allow_html=True)


def detect_mix_type(title: str) -> str:
    t = title.lower()
    if any(x in t for x in ["sparse", "sparce", "sprs", "sp_"]):
        return "sparse"
    if any(x in t for x in ["sound design", "sde", "element"]):
        return "sound_design"
    if any(x in t for x in ["alt mix", "alt master", "no string", "no vocal"]):
        return "alt"
    if any(x in t for x in ["full", "fl_", "master"]):
        return "full"
    return "unknown"


def check_contamination(desc: str, catalog: str) -> list:
    try:
        from engine import THEATRICAL_TERMS, COMMERCIAL_TERMS, THEATRICAL_CATALOGS, COMMERCIAL_CATALOGS
        issues = []
        desc_lower = desc.lower()
        catalog_lower = catalog.lower()
        is_theatrical = any(c in catalog_lower for c in THEATRICAL_CATALOGS)
        is_commercial = any(c in catalog_lower for c in COMMERCIAL_CATALOGS)
        if is_commercial:
            found = [t for t in THEATRICAL_TERMS if t in desc_lower]
            if found:
                issues.append(f"Theatrical language in EPP: {', '.join(found)}")
        if is_theatrical:
            found = [t for t in COMMERCIAL_TERMS if t in desc_lower]
            if found:
                issues.append(f"Commercial language in {catalog}: {', '.join(found)}")
        return issues
    except Exception:
        return []


def context_desc_label(catalog: str) -> str:
    return "Campaign Description" if catalog == "EPP" else "Trailer Description"


def save_to_history(title: str, desc: str):
    if desc and desc.strip():
        if title not in st.session_state.track_history:
            st.session_state.track_history[title] = []
        history = st.session_state.track_history[title]
        if not history or history[-1] != desc:
            history.append(desc)
            if len(history) > 5:
                history.pop(0)


def copy_button(text: str, key: str, label: str = "Copy to Clipboard"):
    escaped = text.replace("`", "\\`").replace("\\", "\\\\")
    st.markdown(f"""
    <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>{{
        document.getElementById('cb_{key}').style.display='inline';
        setTimeout(()=>document.getElementById('cb_{key}').style.display='none', 2000);
    }})" style="cursor:pointer;padding:4px 12px;font-size:0.8rem;margin-bottom:8px;">{label}</button>
    <span id="cb_{key}" style="display:none;color:green;font-size:0.8rem;margin-left:8px;">Copied ✓</span>
    """, unsafe_allow_html=True)


def gemini_source_block(track: dict, catalog: str):
    cdl = context_desc_label(catalog)
    fields = [
        ("Overall Consensus", track.get("Overall Consensus", "")),
        (cdl, track.get(cdl, "")),
        ("Editor Description", track.get("Editor Description", "")),
        ("Supervisor Description", track.get("Supervisor Description", "")),
        ("Keywords", track.get("Keywords", "")),
        ("Tip", track.get("Tip", "")),
    ]
    for label, val in fields:
        if val:
            st.markdown(
                f'<div class="gemini-source-field"><div class="gemini-source-label">{label}</div>{val}</div>',
                unsafe_allow_html=True
            )


def _reset_pipeline():
    st.session_state.pipeline = dict(_PIPE_DEFAULT)


def _auto_save(label: str = ""):
    """Fire-and-forget Dropbox save. Never blocks or crashes the UI."""
    if PERSISTENCE_AVAILABLE and dropbox_token and st.session_state.app_data.get("tracks"):
        save_progress(dropbox_token, st.session_state.app_data, st.session_state.pipeline)
        if label:
            print(f"[PFD] Auto-saved: {label}")


# ── Secrets — resolved before sidebar so controls can reference them ───────────
gemini_api_key = st.secrets.get("GEMINI_API_KEY", None)
claude_api_key  = st.secrets.get("ANTHROPIC_API_KEY", None)
dropbox_token   = st.secrets.get("DROPBOX_TOKEN", None)

# ── Sidebar ────────────────────────────────────────────────────────────────────
catalog = st.session_state.app_data.get("catalog", "EPP")

with st.sidebar:
    st.markdown("### PUBLISHER FINAL DELIVERY")
    st.divider()

    logo_map = {
        "redCola": "redCola logo 200x2001934x751.jpg",
        "SSC": "SSC 200x200 8.27.08#U202fPM.jpg",
        "EPP": "EPP 200x200.jpg",
    }
    try:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        logo_path = os.path.join(base_dir, "01_VISUAL_REFERENCES", catalog, logo_map[catalog])
        if os.path.exists(logo_path):
            st.image(logo_path, width=160)
    except Exception:
        pass

    if catalog:
        st.caption(f"Catalog: **{catalog}**")

    # Pipeline status indicator
    pipe = st.session_state.pipeline
    if pipe["status"] not in ("idle", "done"):
        if pipe["status"] == "processing":
            total = pipe.get("total_to_analyze", 1)
            done = pipe.get("processed_count", 0)
            pct = int(done / total * 100) if total else 0
            st.caption(f"🔄 Pipeline: {pct}% ({done}/{total})")
        elif pipe["status"] == "synthesizing":
            st.caption("🔄 Pipeline: synthesizing...")
        elif pipe["status"] == "error":
            st.caption("❌ Pipeline: error")
        elif pipe["status"] == "crawling":
            st.caption("🔍 Pipeline: scanning...")

    st.divider()

    active_tab = st.radio(
        "Navigate", TABS,
        index=st.session_state.active_tab_index,
        label_visibility="collapsed"
    )
    if TABS.index(active_tab) != st.session_state.active_tab_index:
        st.session_state.active_tab_index = TABS.index(active_tab)
        st.rerun()

    st.divider()

    if st.button("Reset Session"):
        st.session_state.app_data = {
            "tracks": [], "album_description": "", "album_name": "",
            "album_name_selected": "", "cover_art": "", "mailchimp_intro": "",
            "catalog": "EPP",
        }
        st.session_state.dropbox_files = []
        st.session_state.track_history = {}
        st.session_state.active_tab_index = 0
        _reset_pipeline()
        st.session_state.pop("_saved_sessions", None)
        st.success("Session cleared.")

    # ── Persistence Controls ───────────────────────────────────────────────────
    if PERSISTENCE_AVAILABLE and dropbox_token:
        st.divider()
        has_tracks = bool(st.session_state.app_data.get("tracks"))

        col_save, col_restore = st.columns(2)
        with col_save:
            if st.button("💾 Save", disabled=not has_tracks, use_container_width=True,
                         help="Save progress to Dropbox now"):
                with st.spinner("Saving..."):
                    ok = save_progress(
                        dropbox_token,
                        st.session_state.app_data,
                        st.session_state.pipeline,
                    )
                if ok:
                    st.toast("✓ Saved to Dropbox")
                else:
                    st.toast("⚠️ Save failed — check Dropbox token")

        with col_restore:
            if st.button("📂 Restore", use_container_width=True,
                         help="Load a previously saved session"):
                with st.spinner("Checking Dropbox..."):
                    st.session_state["_saved_sessions"] = list_sessions(dropbox_token)

        if st.session_state.get("_saved_sessions"):
            sessions = st.session_state["_saved_sessions"]
            if not sessions:
                st.caption("No saved sessions found.")
            else:
                st.caption(f"{len(sessions)} saved session(s):")
                for i, s in enumerate(sessions):
                    save_dt = s["save_time"][:16].replace("T", " ") if s.get("save_time") else ""
                    st.markdown(f"**{s['display']}**")
                    st.caption(f"{s['stage_summary']} · {save_dt}")
                    if st.button("Restore this session", key=f"restore_{i}"):
                        if s.get("app_data"):
                            st.session_state.app_data = s["app_data"]
                        meta = s.get("pipeline_meta", {})
                        st.session_state.pipeline["album_name"] = s.get("album_name", "")
                        st.session_state.pipeline["catalog"]    = s.get("catalog", "")
                        st.session_state.pipeline["status"]     = "done" if s.get("stages", {}).get("ingest") else "idle"
                        st.session_state.pipeline["processed_count"]  = meta.get("processed_count", 0)
                        st.session_state.pipeline["total_to_analyze"] = meta.get("total_to_analyze", 0)
                        st.session_state.pipeline["album_path"]       = meta.get("album_path", "")
                        st.session_state.pipeline["dropbox_output_path"] = meta.get("album_path", "")
                        st.session_state.active_tab_index = s.get("furthest_tab", 1)
                        st.session_state.pop("_saved_sessions", None)
                        st.rerun()
                    st.divider()

    with st.expander("⚙️ Configuration"):
        gemini_api_key = st.secrets.get("GEMINI_API_KEY", None) or st.text_input(
            "Gemini API Key", type="password", key="gemini_key_input",
            placeholder="For audio analysis"
        )
        claude_api_key = st.secrets.get("ANTHROPIC_API_KEY", None) or st.text_input(
            "Claude API Key", type="password", key="claude_key_input",
            placeholder="For all writing"
        )
        dropbox_token = st.secrets.get("DROPBOX_TOKEN", None) or st.text_input(
            "Dropbox Token", type="password", key="dropbox_key_input",
            placeholder="Required for pipeline"
        )

active_tab_index = st.session_state.active_tab_index


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE AUTO-ADVANCE (runs on every rerun, regardless of active tab)
# Processes one batch, then st.rerun() to continue automatically.
# ══════════════════════════════════════════════════════════════════════════════
if PIPELINE_AVAILABLE and gemini_api_key and dropbox_token:
    pipe = st.session_state.pipeline

    if pipe["status"] == "processing" and pipe["queue"]:
        batch = pipe["queue"][0]

        for entry in batch:
            pipe["current_file"] = entry.display_name
            try:
                ext = os.path.splitext(entry.dropbox_path)[1]
                file_bytes = st.session_state.engine.download_bytes_from_dropbox(
                    dropbox_token, entry.dropbox_path
                )
                pipeline_catalog = pipe["catalog"]
                cdl = st.session_state.engine._context_desc_label(pipeline_catalog)

                if entry.category in ("full_mix", "sparse_mix"):
                    metadata = st.session_state.engine.analyze_audio_bytes(
                        file_bytes, ext, entry.display_name, pipeline_catalog, gemini_api_key
                    )
                    if metadata:
                        existing_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                        if entry.display_name not in existing_titles:
                            st.session_state.app_data["tracks"].append({
                                "Title": entry.display_name,
                                "Mix Type": entry.mix_type,
                                "Overall Consensus": metadata.get("Overall Consensus", ""),
                                cdl: metadata.get(cdl, ""),
                                "Editor Description": metadata.get("Editor Description", ""),
                                "Supervisor Description": metadata.get("Supervisor Description", ""),
                                "Keywords": metadata.get("Keywords", ""),
                                "Tip": metadata.get("Tip", ""),
                                "Track Description": "",
                            })
                        pipe["log"].append(f"✓ {entry.display_name} [{entry.mix_type}]")

                elif entry.category == "sound_design":
                    sde_data = st.session_state.engine.analyze_sound_design_element(
                        file_bytes, ext, entry.display_name, gemini_api_key
                    )
                    if sde_data:
                        desc = ""
                        if claude_api_key:
                            desc = st.session_state.engine.synthesize_sound_design_description(
                                entry.display_name, entry.parent_track, sde_data, claude_api_key
                            )
                        existing_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                        if entry.display_name not in existing_titles:
                            st.session_state.app_data["tracks"].append({
                                "Title": entry.display_name,
                                "Mix Type": "Sound Design",
                                "Overall Consensus": sde_data.get("Sonic_Character", ""),
                                "Trailer Description": sde_data.get("Best_Usage", ""),
                                "Editor Description": sde_data.get("Unique_Qualities", ""),
                                "Supervisor Description": sde_data.get("Technical_Notes", ""),
                                "Keywords": sde_data.get("Keywords", ""),
                                "Tip": sde_data.get("Element_Type", ""),
                                "Track Description": desc,
                            })
                        pipe["log"].append(f"✓ SDE: {entry.display_name} ({entry.parent_track})")

            except Exception as exc:
                err_str = str(exc)
                pipe["log"].append(f"❌ {entry.display_name}: {err_str[:100]}")
                if is_quota_error(exc):
                    pipe["status"] = "error"
                    pipe["error"] = (
                        f"Gemini quota/billing error on '{entry.display_name}': {err_str}\n"
                        "Top up Gemini API credits and restart the pipeline."
                    )
                    send_ntfy(
                        "⚠️ PFD — Gemini quota exhausted",
                        f"Pipeline stopped at '{entry.display_name}'.\n"
                        f"{pipe['processed_count']}/{pipe['total_to_analyze']} files done.\n"
                        "Top up Gemini API credits and restart.",
                        priority="urgent",
                    )
                    break  # Stop processing this batch

        if pipe["status"] != "error":
            pipe["queue"].pop(0)
            pipe["processed_count"] += len(batch)

            # Heartbeat ntfy every 10 batches
            pipe["heartbeat_count"] += 1
            if pipe["heartbeat_count"] % 10 == 0:
                send_ntfy(
                    "PFD Pipeline — in progress",
                    f"{pipe['album_name']} ({pipe['catalog']})\n"
                    f"{pipe['processed_count']}/{pipe['total_to_analyze']} files done",
                )

            if not pipe["queue"]:
                pipe["status"] = "synthesizing"

            # Auto-save after every batch so no work is ever lost
            if PERSISTENCE_AVAILABLE and dropbox_token:
                save_progress(dropbox_token, st.session_state.app_data, pipe)

            st.rerun()

    elif pipe["status"] == "synthesizing":
        pipeline_catalog = pipe["catalog"]
        if claude_api_key:
            tracks_to_synthesize = [
                t for t in st.session_state.app_data["tracks"]
                if not t.get("Track Description") and t.get("Overall Consensus")
                and t.get("Mix Type") != "Sound Design"
            ]
            for track in tracks_to_synthesize:
                master = st.session_state.engine.synthesize_master_description(
                    track["Title"], track, pipeline_catalog, claude_api_key,
                    mix_type=track.get("Mix Type", "unknown"),
                )
                track["Track Description"] = master

        pipe["status"] = "done"
        # Save final state after synthesis completes
        if PERSISTENCE_AVAILABLE and dropbox_token:
            save_progress(dropbox_token, st.session_state.app_data, pipe)
        track_count = len(st.session_state.app_data["tracks"])
        send_ntfy(
            "✅ PFD Pipeline — complete",
            f"{pipe.get('album_name', 'Album')} ({pipe.get('catalog', '')})\n"
            f"{pipe['processed_count']} files analyzed, {track_count} tracks ready.\n"
            "Open the app to review and export.",
            priority="high",
        )
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 00 · HOME
# ══════════════════════════════════════════════════════════════════════════════
if active_tab_index == 0:
    st.markdown("""
    <h1 style='color:#cc0000;font-size:2.2rem;font-weight:800;letter-spacing:-0.02em;margin-bottom:0.25rem;'>
    PUBLISHER FINAL DELIVERY
    </h1>
    """, unsafe_allow_html=True)
    st.divider()
    for num, name, desc in [
        ("01", "Ingest Audio", "Paste a Dropbox link — pipeline auto-crawls, analyzes, and synthesizes. Or upload files manually."),
        ("02", "Track Descriptions", "Claude synthesizes all 6 Gemini fields into one definitive master description."),
        ("03", "Album Description", "Claude synthesises the album arc from all master descriptions."),
        ("04", "Album Name", "Claude generates original title concepts. Select one to carry forward."),
        ("05", "Cover Art Prompts", "Claude writes MidJourney v7 prompts with copy buttons."),
        ("06", "MailChimp Intro", "Claude writes the editorial memo for supervisors."),
        ("07", "Fix Existing Copy", "Paste any bad copy — Claude rewrites it through the Council."),
        ("08", "Export", "Clean Room validation → unified CSV + ZIP file."),
    ]:
        st.markdown(f"`{num}` **{name}** — {desc}")

    next_button("Start → 01 · Ingest Audio")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 01 · INGEST AUDIO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 1:
    st.title("01 · INGEST AUDIO")

    st.subheader("Select Catalog")
    catalog_choice = st.selectbox(
        "Active Catalog", ["EPP", "redCola", "SSC"],
        index=["EPP", "redCola", "SSC"].index(st.session_state.app_data.get("catalog", "EPP")),
        label_visibility="collapsed"
    )
    if catalog_choice != st.session_state.app_data.get("catalog"):
        st.session_state.app_data["catalog"] = catalog_choice
        catalog = catalog_choice
        st.rerun()

    catalog = st.session_state.app_data.get("catalog", "EPP")
    cdl = context_desc_label(catalog)
    st.divider()

    mode = st.radio("Input mode", ["🔗 Dropbox Pipeline", "📁 Manual Upload"], horizontal=True)

    if mode == "🔗 Dropbox Pipeline":
        # ── Dropbox Pipeline UI ────────────────────────────────────────────────
        if not PIPELINE_AVAILABLE:
            st.error("Pipeline module unavailable. Check that dropbox_pipeline.py is deployed.")
        elif not dropbox_token:
            st.error("Dropbox token required. Open ⚙️ Configuration in the sidebar.")
        elif not gemini_api_key:
            st.error("Gemini API key required. Open ⚙️ Configuration in the sidebar.")
        else:
            pipe = st.session_state.pipeline

            if pipe["status"] == "idle":
                st.markdown(
                    "Paste a shared Dropbox link to an album folder from the **Quality Checked** folder. "
                    "Catalog is auto-detected from the path."
                )
                shared_link = st.text_input(
                    "Dropbox shared link",
                    placeholder="https://www.dropbox.com/scl/fo/...",
                    key="pipeline_link_input",
                )
                if shared_link and shared_link.strip():
                    pipe["shared_link"] = shared_link.strip()
                    pipe["status"] = "crawling"
                    st.rerun()

            elif pipe["status"] == "crawling":
                st.info(f"🔍 Scanning folder structure...")
                with st.spinner("Resolving link and crawling..."):
                    try:
                        dbx = st.session_state.engine.get_dropbox_client(dropbox_token)
                        album_path = resolve_shared_link(dbx, pipe["shared_link"])
                        pipe["album_path"] = album_path
                        pipe["dropbox_output_path"] = album_path

                        detected_catalog = detect_catalog_from_path(album_path)
                        pipe["catalog"] = detected_catalog
                        if detected_catalog != "unknown":
                            st.session_state.app_data["catalog"] = detected_catalog

                        if not is_quality_checked(album_path):
                            st.warning(
                                "⚠️ This link doesn't appear to be in a Quality Checked folder. "
                                "Make sure you're using the right link."
                            )

                        crawl = crawl_album_folder(dbx, album_path, detected_catalog)
                        pipe["crawl_log"] = crawl.log
                        pipe["album_name"] = crawl.album_name

                        # Add auto-described entries (alt mixes, cutdowns) immediately
                        pipe_cdl = st.session_state.engine._context_desc_label(detected_catalog)
                        for entry in crawl.auto_described:
                            if entry.category == "alt_mix":
                                desc = generate_alt_description(entry.parent_track, entry.notes)
                            else:
                                desc = generate_cutdown_description(entry.parent_track, entry.notes)
                            existing_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                            if entry.display_name not in existing_titles:
                                st.session_state.app_data["tracks"].append({
                                    "Title": entry.display_name,
                                    "Mix Type": entry.mix_type,
                                    "Overall Consensus": "",
                                    pipe_cdl: "",
                                    "Editor Description": "",
                                    "Supervisor Description": "",
                                    "Keywords": "",
                                    "Tip": "",
                                    "Track Description": desc,
                                })

                        analyzable = crawl.analyzable
                        batches = make_batches(analyzable)
                        pipe["queue"] = batches
                        pipe["total_to_analyze"] = len(analyzable)
                        pipe["processed_count"] = 0
                        pipe["log"] = [
                            f"Catalog: {detected_catalog}",
                            f"Album: {crawl.album_name}",
                            crawl.summary(),
                            "─" * 40,
                        ]
                        pipe["heartbeat_count"] = 0
                        pipe["status"] = "processing"

                    except Exception as e:
                        pipe["status"] = "error"
                        pipe["error"] = str(e)

                st.rerun()

            elif pipe["status"] in ("processing", "synthesizing"):
                total = pipe["total_to_analyze"]
                done = pipe["processed_count"]
                prog = done / total if total else 0

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"**{pipe.get('album_name', 'Album')}** · {pipe.get('catalog', '')}")
                with col2:
                    st.caption(f"{done}/{total} files")

                st.progress(prog)

                if pipe["status"] == "processing" and pipe.get("current_file"):
                    st.caption(f"Analyzing: {pipe['current_file']}")
                elif pipe["status"] == "synthesizing":
                    st.info("Gemini complete — Claude synthesizing master descriptions...")

                with st.expander("Processing log", expanded=True):
                    log_text = "\n".join(pipe["log"][-30:])
                    st.markdown(f'<div class="pipeline-log">{log_text}</div>', unsafe_allow_html=True)

                st.info("Processing in background — you can navigate to other tabs. An ntfy notification will fire when complete.")

            elif pipe["status"] == "done":
                track_count = len(st.session_state.app_data["tracks"])
                st.success(
                    f"✅ **Pipeline complete** — {pipe['processed_count']} files analyzed, "
                    f"{track_count} total tracks ready."
                )
                st.caption(f"Album: {pipe.get('album_name', '')} | Catalog: {pipe.get('catalog', '')}")

                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("→ Review Descriptions (Tab 02)", type="primary"):
                        go_to_tab(2)
                with col_b:
                    if st.button("Run New Album"):
                        _reset_pipeline()
                        st.rerun()

                with st.expander("Full processing log"):
                    log_text = "\n".join(pipe["log"])
                    st.markdown(f'<div class="pipeline-log">{log_text}</div>', unsafe_allow_html=True)

            elif pipe["status"] == "error":
                st.error(f"❌ Pipeline error:\n\n{pipe.get('error', 'Unknown error')}")
                if st.button("Reset Pipeline"):
                    _reset_pipeline()
                    st.rerun()

    else:
        # ── Manual Upload UI ───────────────────────────────────────────────────
        if not gemini_api_key:
            st.error("Gemini API key required. Open ⚙️ Configuration in the sidebar.")
            st.stop()

        st.subheader("Upload Files")
        st.caption(f"Gemini produces 6 fields per track: Overall Consensus, {cdl}, "
                   "Editor Description, Supervisor Description, Keywords, Tip.")
        uploaded_files = st.file_uploader(
            "Drag audio files here", type=["mp3", "wav", "aif", "aiff", "flac"],
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
                    safe_path = f"/tmp/{clean_title}{file_ext}"
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
                                    "Mix Type": detect_mix_type(clean_title),
                                    "Overall Consensus": metadata.get("Overall Consensus", ""),
                                    cdl: metadata.get(cdl, ""),
                                    "Editor Description": metadata.get("Editor Description", ""),
                                    "Supervisor Description": metadata.get("Supervisor Description", ""),
                                    "Keywords": metadata.get("Keywords", ""),
                                    "Tip": metadata.get("Tip", ""),
                                    "Track Description": "",
                                })
                    except Exception as e:
                        import traceback
                        st.session_state.ingestion_error = f"Failed: {clean_title}\n{traceback.format_exc()}"
                    finally:
                        if os.path.exists(safe_path):
                            os.remove(safe_path)
                    progress.progress((idx + 1) / len(uploaded_files))
                st.success("Analysis complete. Go to Tab 02 to synthesize master descriptions.")
                st.rerun()

        if st.button("Analyse with Gemini", disabled=not uploaded_files):
            run_analysis_dialog()

    if st.session_state.ingestion_error:
        st.error(st.session_state.ingestion_error)
        if st.button("Dismiss"):
            st.session_state.ingestion_error = None
            st.rerun()

    st.divider()
    st.subheader("Track Data")
    if st.session_state.app_data["tracks"]:
        summary_rows = []
        for t in st.session_state.app_data["tracks"]:
            summary_rows.append({
                "Title": t.get("Title", ""),
                "Mix Type": t.get("Mix Type", ""),
                "Keywords": t.get("Keywords", ""),
                "Gemini": "✓" if t.get("Overall Consensus") else "—",
                "Description": "✓" if t.get("Track Description") else "—",
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True)

        with st.expander("View full Gemini output per track"):
            for t in st.session_state.app_data["tracks"]:
                st.markdown(f"**{t.get('Title', '')}** · `{t.get('Mix Type', '')}`")
                gemini_source_block(t, catalog)
                st.divider()

        csv = pd.DataFrame(st.session_state.app_data["tracks"]).to_csv(index=False).encode("utf-8")
        st.download_button("Download Raw Data CSV", csv, "Raw_Track_Data.csv", "text/csv")
    else:
        st.info("No tracks ingested yet.")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 02 · TRACK DESCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 2:
    st.title("02 · TRACK DESCRIPTIONS")
    st.caption("Claude synthesizes all 6 Gemini fields into one definitive 3-sentence master description.")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    if not st.session_state.app_data["tracks"]:
        st.warning("Ingest tracks in Tab 01 first.")
        next_button()
        st.stop()
    if not claude_api_key:
        st.error("Claude API key required. Open ⚙️ Configuration in the sidebar.")
        next_button()
        st.stop()

    col_action, col_editor = st.columns([1, 1])

    with col_action:
        st.subheader("Synthesize Master Descriptions")
        tracks = st.session_state.app_data["tracks"]
        full_count = sum(1 for t in tracks if t.get("Mix Type") == "full")
        sparse_count = sum(1 for t in tracks if t.get("Mix Type") == "sparse")
        sde_count = sum(1 for t in tracks if t.get("Mix Type") == "sound_design")
        if full_count or sparse_count:
            st.caption(f"Detected: {full_count} full · {sparse_count} sparse · {sde_count} sound design")

        pending = sum(
            1 for t in tracks
            if not t.get("Track Description") and t.get("Mix Type") not in ("alt", "sound_design")
        )
        if pending:
            st.info(f"{pending} track(s) pending synthesis.")

        if st.button("Synthesize All", type="primary"):
            with st.spinner("Council synthesizing..."):
                updated = []
                prog = st.progress(0)
                for idx, track in enumerate(tracks):
                    if track.get("Mix Type") in ("sound_design",):
                        updated.append(track)
                        prog.progress((idx + 1) / len(tracks))
                        continue
                    if not track.get("Overall Consensus") and track.get("Track Description"):
                        updated.append(track)
                        prog.progress((idx + 1) / len(tracks))
                        continue
                    save_to_history(track["Title"], track.get("Track Description", ""))
                    master = st.session_state.engine.synthesize_master_description(
                        track["Title"], track, catalog, claude_api_key,
                        mix_type=track.get("Mix Type", "unknown"),
                    )
                    track["Track Description"] = master
                    updated.append(track)
                    prog.progress((idx + 1) / len(tracks))
                st.session_state.app_data["tracks"] = updated
            _auto_save("Tab 02 synthesize all")
            st.success("All master descriptions synthesized.")
            st.rerun()

        st.divider()
        st.subheader("Synthesize Single Track")
        track_titles = [t["Title"] for t in tracks]
        selected_track = st.selectbox("Select track", track_titles)
        if st.button("Synthesize Selected"):
            with st.spinner("Synthesizing..."):
                track = next(t for t in tracks if t["Title"] == selected_track)
                save_to_history(track["Title"], track.get("Track Description", ""))
                master = st.session_state.engine.synthesize_master_description(
                    track["Title"], track, catalog, claude_api_key,
                    mix_type=track.get("Mix Type", "unknown"),
                )
                track["Track Description"] = master
            _auto_save("Tab 02 single track")
            st.success(f"'{selected_track}' updated.")
            st.rerun()

    with col_editor:
        st.subheader("Master Descriptions")
        for track in st.session_state.app_data["tracks"]:
            title = track["Title"]
            mix_type = track.get("Mix Type", "unknown")
            desc = track.get("Track Description", "")

            badge = ""
            if mix_type == "full":
                badge = "<span class='mix-badge-full'>FULL</span>"
            elif mix_type == "sparse":
                badge = "<span class='mix-badge-sparse'>SPARSE</span>"
            elif mix_type == "sound_design":
                badge = "<span class='mix-badge-sde'>SDE</span>"
            elif mix_type == "alt":
                badge = "<span class='mix-badge-alt'>ALT</span>"

            st.markdown(f"**{title}**{badge}", unsafe_allow_html=True)

            if desc:
                issues = check_contamination(desc, catalog)
                for issue in issues:
                    st.markdown(f"<div class='contamination-warn'>⚠️ {issue}</div>", unsafe_allow_html=True)

            new_desc = st.text_area(
                f"desc_{title}", value=desc, height=100,
                label_visibility="collapsed", key=f"desc_edit_{title}"
            )
            if new_desc != desc:
                track["Track Description"] = new_desc

            has_gemini = bool(track.get("Overall Consensus"))
            with st.expander(f"Gemini source data {'✓' if has_gemini else '(not yet ingested)'}"):
                if has_gemini:
                    gemini_source_block(track, catalog)
                else:
                    st.caption("Re-ingest this track in Tab 01 to get the 6-field Gemini output.")

            history = st.session_state.track_history.get(title, [])
            if history:
                with st.expander(f"Previous versions ({len(history)})"):
                    for i, old_desc in enumerate(reversed(history)):
                        st.caption(f"Version {len(history) - i}")
                        st.text(old_desc)
                        if st.button("Restore", key=f"restore_{title}_{i}"):
                            save_to_history(title, desc)
                            track["Track Description"] = old_desc
                            st.rerun()
            st.divider()

        csv = pd.DataFrame(st.session_state.app_data["tracks"]).to_csv(index=False).encode("utf-8")
        st.download_button("Download Descriptions CSV", csv, "Descriptions.csv", "text/csv")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 03 · ALBUM DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 3:
    st.title("03 · ALBUM DESCRIPTION")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Synthesise from Master Descriptions")
        track_count = len(st.session_state.app_data["tracks"])
        if track_count == 0:
            st.warning("No tracks loaded. Complete Tab 01 first.")
        else:
            ready = sum(1 for t in st.session_state.app_data["tracks"] if t.get("Track Description"))
            st.write(f"Synthesising from {ready} of {track_count} track(s) with master descriptions.")
            if st.button("Generate Album Description", type="primary"):
                with st.spinner("Council synthesising..."):
                    descs = [t.get("Track Description", "") for t in st.session_state.app_data["tracks"]]
                    result = st.session_state.engine.generate_album_description(descs, catalog, claude_api_key)
                    st.session_state.app_data["album_description"] = result
                _auto_save("Tab 03 album description")
                st.rerun()

    with col_output:
        st.subheader("Output")
        edited = st.text_area(
            "Album Description", value=st.session_state.app_data["album_description"],
            height=150, label_visibility="collapsed",
        )
        st.session_state.app_data["album_description"] = edited
        if edited:
            copy_button(edited, "album_desc")
            st.download_button("Download TXT", edited.encode("utf-8"), "Album_Description.txt", "text/plain")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 04 · ALBUM NAME
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 4:
    st.title("04 · ALBUM NAME")
    catalog = st.session_state.app_data.get("catalog", "EPP")

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
                st.session_state.app_data["album_name_selected"] = ""
            _auto_save("Tab 04 album name generated")
            st.rerun()

    with col_output:
        st.subheader("Select a Title")
        raw = st.session_state.app_data.get("album_name", "")

        if raw:
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            options = []
            rationales = {}
            current_title = None
            for line in lines:
                m = re.match(r"^\d+[\.\)]\s*(.+)$", line)
                if m:
                    current_title = m.group(1).strip()
                    options.append(current_title)
                    rationales[current_title] = ""
                elif current_title and line and not re.match(r"^\d+[\.\)]", line):
                    rationales[current_title] = line

            if options:
                current_selection = st.session_state.app_data.get("album_name_selected", "")
                default_idx = options.index(current_selection) if current_selection in options else 0
                selected = st.radio("Choose the title to carry forward:", options, index=default_idx)
                if selected:
                    if selected != st.session_state.app_data.get("album_name_selected"):
                        st.session_state.app_data["album_name_selected"] = selected
                        _auto_save("Tab 04 album name selected")
                    if rationales.get(selected):
                        st.caption(rationales[selected])
                    st.success(f"Selected: **{selected}**")
                copy_button(selected or "", "album_name")
            else:
                edited = st.text_area("Concepts", value=raw, height=220, label_visibility="collapsed")
                st.session_state.app_data["album_name"] = edited
                copy_button(edited, "album_name")
        else:
            st.info("Generate concepts first.")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 05 · COVER ART PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 5:
    st.title("05 · COVER ART PROMPTS")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    album_name_for_art = (
        st.session_state.app_data.get("album_name_selected") or
        st.session_state.app_data.get("album_name", "")
    )

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Generate MidJourney v7 Prompts")
        if album_name_for_art:
            st.caption(f"Using album name: **{album_name_for_art}**")
        else:
            st.warning("No album name selected. Complete Tab 04 first.")
        st.write("4 prompts. Different framing, texture, and light source each.")

        if st.button("Generate Prompts", type="primary"):
            with st.spinner("Art Director working..."):
                refs = []
                cat_folder = st.session_state.engine.root_path / "01_VISUAL_REFERENCES" / catalog
                if cat_folder.exists():
                    refs = [
                        f"https://placeholder.url/{f.name}"
                        for f in cat_folder.iterdir()
                        if f.is_file() and not f.name.startswith(".")
                    ]
                if not refs:
                    refs = ["https://dummy.url/ref1.jpg"] * 4
                selected_refs = random.choices(refs, k=4)

                track_descriptions = [t.get("Track Description", "") for t in st.session_state.app_data["tracks"]]
                keywords = ", ".join([t.get("Keywords", "") for t in st.session_state.app_data["tracks"] if t.get("Keywords")])

                result = st.session_state.engine.generate_cover_art_prompts(
                    album_name_for_art,
                    st.session_state.app_data["album_description"],
                    catalog, selected_refs, claude_api_key,
                    track_descriptions=track_descriptions,
                    keywords=keywords,
                )
                st.session_state.app_data["cover_art"] = result
            _auto_save("Tab 05 cover art")
            st.rerun()

        st.divider()
        st.caption("Replace `--sref [URL]` placeholders with actual reference image URLs before using in MidJourney.")

    with col_output:
        st.subheader("Prompts")
        edited = st.text_area(
            "MidJourney Prompts", value=st.session_state.app_data["cover_art"],
            height=400, label_visibility="collapsed",
        )
        st.session_state.app_data["cover_art"] = edited
        if edited:
            prompts = [p.strip() for p in edited.split("\n\n") if p.strip()]
            for i, p in enumerate(prompts):
                copy_button(p, f"prompt_{i}", f"Copy Prompt {i+1}")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 06 · MAILCHIMP INTRO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 6:
    st.title("06 · MAILCHIMP INTRO")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    album_name_for_mail = (
        st.session_state.app_data.get("album_name_selected") or
        st.session_state.app_data.get("album_name", "")
    )

    col_action, col_output = st.columns([1, 1])

    with col_action:
        st.subheader("Generate Editorial Memo")
        if album_name_for_mail:
            st.caption(f"Using album name: **{album_name_for_mail}**")
        st.write("Identifies the editor's pain point first. No sales pitch.")
        if st.button("Write MailChimp Intro", type="primary"):
            with st.spinner("Copywriter drafting..."):
                track_descriptions = [t.get("Track Description", "") for t in st.session_state.app_data["tracks"]]
                result = st.session_state.engine.generate_mailchimp_intro(
                    album_name_for_mail,
                    st.session_state.app_data["album_description"],
                    catalog, claude_api_key,
                    track_descriptions=track_descriptions,
                )
                st.session_state.app_data["mailchimp_intro"] = result
            _auto_save("Tab 06 mailchimp")
            st.rerun()

    with col_output:
        st.subheader("Output")
        intro = st.session_state.app_data.get("mailchimp_intro", "")
        if intro:
            st.markdown(
                f'<div class="mailchimp-output">{intro.replace(chr(10), "<br>")}</div>',
                unsafe_allow_html=True
            )
            copy_button(intro, "mailchimp")
            st.download_button("Download TXT", intro.encode("utf-8"), "MailChimp_Intro.txt", "text/plain")

        edited = st.text_area("Edit if needed", value=intro, height=200)
        if edited != intro:
            st.session_state.app_data["mailchimp_intro"] = edited

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 07 · FIX EXISTING COPY
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 7:
    st.title("07 · FIX EXISTING COPY")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()

    st.write("Paste any copy that isn't working. Claude rewrites it through the full Council filter.")

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
                    st.session_state.app_data["album_name_selected"] = result
                    st.success("Applied.")
                if content_type == "Track Description":
                    track_titles = [t["Title"] for t in st.session_state.app_data["tracks"]]
                    if track_titles:
                        apply_track = st.selectbox("Apply to track:", track_titles, key="apply_track")
                        if st.button("→ Apply to Track"):
                            for t in st.session_state.app_data["tracks"]:
                                if t["Title"] == apply_track:
                                    save_to_history(apply_track, t.get("Track Description", ""))
                                    t["Track Description"] = result
                            st.success(f"Applied to '{apply_track}'.")
        else:
            st.info("Refined output will appear here.")

    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 08 · EXPORT
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 8:
    st.title("08 · EXPORT")
    catalog = st.session_state.app_data.get("catalog", "EPP")

    st.subheader("Clean Room Validator")
    passed, errors = st.session_state.engine.validate_data(st.session_state.app_data, catalog)

    if not passed:
        st.error(f"{len(errors)} error(s) blocking export:")
        for msg in errors:
            st.warning(msg)
    else:
        st.success("Clean Room passed ✓ — all checks clear.")

        album_name_safe = (
            st.session_state.app_data.get("album_name_selected") or
            st.session_state.app_data.get("album_name", "album")
        ).split("\n")[0][:30].strip()

        zip_buffer = st.session_state.engine.compile_final_package(
            st.session_state.app_data, catalog=catalog
        )
        st.download_button(
            label="Download Final Delivery ZIP",
            data=zip_buffer,
            file_name=f"{catalog}_{album_name_safe}_Final_Delivery.zip",
            mime="application/zip",
            type="primary",
        )
        st.caption("ZIP contains: Track_Data.csv, Album_Description.txt, Album_Name.txt, MidJourney_Prompts.txt, MailChimp_Copy.txt")

        # Save ZIP back to Dropbox album folder
        pipe = st.session_state.pipeline
        if dropbox_token and pipe.get("dropbox_output_path") and pipe.get("status") == "done":
            st.divider()
            st.subheader("Save to Dropbox")
            dest_path = f"{pipe['dropbox_output_path']}/{catalog}_{album_name_safe}_Final_Delivery.zip"
            st.caption(f"Destination: `{dest_path}`")
            if st.button("Upload ZIP to Dropbox Album Folder"):
                with st.spinner("Uploading..."):
                    try:
                        zip_buffer.seek(0)
                        st.session_state.engine.upload_bytes_to_dropbox(
                            dropbox_token, zip_buffer.read(), dest_path
                        )
                        st.success(f"Uploaded to Dropbox.")
                        send_ntfy(
                            "📦 PFD — ZIP uploaded",
                            f"{catalog}_{album_name_safe}_Final_Delivery.zip saved to Dropbox album folder.",
                        )
                    except Exception as e:
                        st.error(str(e))

        elif dropbox_token:
            st.divider()
            st.subheader("Save to Dropbox")
            output_folder = st.text_input("Dropbox output folder", value="/Publisher Output")
            dest_path = f"{output_folder}/{catalog}_{album_name_safe}_Final_Delivery.zip"
            if st.button("Upload ZIP to Dropbox"):
                with st.spinner("Uploading..."):
                    try:
                        import tempfile
                        zip_buffer.seek(0)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
                            tmp.write(zip_buffer.read())
                            tmp_path = tmp.name
                        st.session_state.engine.upload_to_dropbox(dropbox_token, tmp_path, dest_path)
                        os.remove(tmp_path)
                        st.success(f"Uploaded to Dropbox: `{dest_path}`")
                    except Exception as e:
                        st.error(str(e))

    st.divider()
    st.subheader("Session Summary")
    data = st.session_state.app_data
    tracks = data.get("tracks", [])
    master_ready = sum(1 for t in tracks if t.get("Track Description"))
    gemini_ready = sum(1 for t in tracks if t.get("Overall Consensus"))
    sde_count = sum(1 for t in tracks if t.get("Mix Type") == "sound_design")
    cols = st.columns(4)
    cols[0].metric("Total Tracks", len(tracks))
    cols[1].metric("Gemini Fields", f"{gemini_ready}/{len(tracks)}")
    cols[2].metric("Descriptions", f"{master_ready}/{len(tracks)}")
    cols[3].metric("Sound Design", sde_count)
