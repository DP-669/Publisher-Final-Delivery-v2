"""
Publisher Final Delivery — v3.

- Tab 01: Gemini analysis behind the hallucination gate. Every track is PASSED or BLOCKED.
- Tabs 02–07: Claude writes under PFD_RULES.md (track descriptions per `track_writer`).
- Tab 08: one ZIP; the untouched DRAFT CSV is written to Dropbox on export.
- Sidebar: rules version, model badges, Dropbox status, BLOCKED count, writer test, FINAL upload.
"""
import datetime
import os
import random
import re
import time

import pandas as pd
import streamlit as st

import capture
import feedback
import gate
import models as model_registry
import rules
from dropbox_pipeline import (
    crawl_album_folder, detect_catalog_from_path, generate_alt_description,
    generate_cutdown_description, is_quality_checked, is_quota_error, make_batches,
    resolve_shared_link, send_ntfy,
)
from engine import (
    CLAUDE_PIN_EXPLICIT, CLAUDE_WRITING_MODEL, GEMINI_AUDIO_MODEL, GEMINI_PIN_EXPLICIT,
    WRITER_MODES, ClaudeError, IngestionEngine, _secret_value, base_title,
)
from persistence import list_sessions, save_progress
from pfd_errors import report

st.set_page_config(
    page_title="Publisher Final Delivery",
    page_icon="🎵",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Styling ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    html, body, [class*="css"] { font-size: 16px !important; }
    .stMarkdown, .stText, p, li, div { font-size: 16px !important; }
    [data-testid="collapsedControl"] { display: block !important; }
    .block-container { max-width: 900px; padding: 2rem 2rem; }
    @media (max-width: 768px) { .block-container { max-width: 100%; padding: 1rem 0.75rem; } }
    .stSidebar .block-container { max-width: 100%; }
    .stTextArea textarea { width: 100% !important; }
    @media (max-width: 640px) { [data-testid="column"] { width: 100% !important; flex: 1 1 100% !important; } }
    .mailchimp-output { white-space: pre-wrap; font-family: Georgia, serif; line-height: 1.8; padding: 1.5rem;
        border: 1px solid #e0e0e0; border-radius: 6px; background: #fafafa; margin-bottom: 1rem; }
    .pfd-warn { background:#fff3cd;border:1px solid #ffc107;border-left:4px solid #ff6b35;border-radius:4px;
        padding:0.4rem 0.8rem;font-size:0.85rem;margin:0.3rem 0 0.5rem 0; }
    .pfd-badge { display:inline-block;border-radius:4px;padding:2px 8px;font-size:0.75rem;font-weight:700;margin:2px 0; }
    .next-button-container { margin-top: 2.5rem; padding-top: 1.5rem; border-top: 1px solid #e0e0e0; }
    .source-field { background:#f8f9fa;border-left:3px solid #dee2e6;padding:0.5rem 0.75rem;margin-bottom:0.4rem;
        font-size:0.85rem;border-radius:0 4px 4px 0; }
    .source-label { font-size:0.7rem;font-weight:700;color:#6c757d;text-transform:uppercase;letter-spacing:0.05em; }
    .pipeline-log { font-family:monospace;font-size:0.78rem;background:#f8f8f8;padding:0.75rem;border-radius:4px;
        max-height:220px;overflow-y:auto;white-space:pre-wrap; }
</style>
""", unsafe_allow_html=True)

TABS = [
    "00 · Home",
    "01 · Ingest Audio",
    "02 · Track Descriptions",
    "03 · Lane & Album Description",
    "04 · Album Name",
    "05 · Cover Art Prompts",
    "06 · MailChimp Intro",
    "07 · Fix Existing Copy",
    "08 · Export",
]
CATALOGS = ["EPP", "redCola", "SSC"]

# ── Session state ──────────────────────────────────────────────────────────────
if "engine" not in st.session_state:
    st.session_state.engine = IngestionEngine()
eng: IngestionEngine = st.session_state.engine

_defaults = {
    "app_data": {"tracks": [], "album_description": "", "album_name": "", "album_name_selected": "",
                 "album_name_candidates": [], "cover_art": "", "mailchimp_intro": "", "catalog": "EPP"},
    "active_tab_index": 0,
    "track_history": {},
    "album_desc_iterations": {},
    "last_auto_save": 0.0,
    "_auto_restored": False,
    "writer_test_state": {},
    "pfd_errors": [],
}
for _k, _v in _defaults.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

_PIPE_DEFAULT = {
    "status": "idle",        # idle | crawling | processing | synthesizing | done | error
    "shared_link": "", "album_path": "", "album_name": "", "catalog": "",
    "crawl_log": [], "queue": [], "processed_count": 0, "total_to_analyze": 0,
    "current_file": "", "log": [], "error": "", "heartbeat_count": 0,
}
if "pipeline" not in st.session_state:
    st.session_state.pipeline = dict(_PIPE_DEFAULT)

app_data = st.session_state.app_data


# ── Helpers ────────────────────────────────────────────────────────────────────
def go_to_tab(index: int):
    st.session_state.active_tab_index = index
    st.rerun()


def next_button(label_override: str = None):
    current = st.session_state.active_tab_index
    if current < len(TABS) - 1:
        label = label_override or f"Next → {TABS[current + 1]}"
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
    return "full"


def status_badge(status: str) -> str:
    if status == gate.PASSED:
        return '<span class="pfd-badge" style="background:#e8f5e9;color:#1b5e20;">PASSED</span>'
    return '<span class="pfd-badge" style="background:#ffebee;color:#b71c1c;">BLOCKED</span>'


def save_to_history(title: str, desc: str):
    if desc and desc.strip():
        history = st.session_state.track_history.setdefault(title, [])
        if not history or history[-1] != desc:
            history.append(desc)
            del history[:-5]


def copy_button(text: str, key: str, label: str = "Copy to Clipboard"):
    escaped = text.replace("\\", "\\\\").replace("`", "\\`").replace("$", "\\$")
    st.markdown(f"""
    <button onclick="navigator.clipboard.writeText(`{escaped}`).then(()=>{{
        document.getElementById('cb_{key}').style.display='inline';
        setTimeout(()=>document.getElementById('cb_{key}').style.display='none', 2000);
    }})" style="cursor:pointer;padding:4px 12px;font-size:0.8rem;margin-bottom:8px;">{label}</button>
    <span id="cb_{key}" style="display:none;color:green;font-size:0.8rem;margin-left:8px;">Copied ✓</span>
    """, unsafe_allow_html=True)


def analysis_block(track: dict, catalog: str):
    ctx = capture.context_label(catalog)
    fields = [
        ("Duration (file)", track.get("Duration", "")),
        ("Ending", track.get("Ending Type", "")),
        ("Events", track.get("Events", "")),
        ("Job", track.get("Overall Consensus", "")),
        (ctx, track.get(ctx, "")),
        ("Editor", track.get("Editor Description", "")),
        ("Supervisor", track.get("Supervisor Description", "")),
        ("Keywords", track.get("Keywords", "")),
        ("Tip", track.get("Tip", "")),
        ("Gemini description", track.get("Gemini Description", "")),
    ]
    facts = (track.get("analysis") or {}).get("facts")
    if facts:
        fields.insert(3, ("Facts", ", ".join(f"{k}: {v}" for k, v in facts.items())))
    for label, val in fields:
        if val:
            st.markdown(f'<div class="source-field"><div class="source-label">{label}</div>{val}</div>',
                        unsafe_allow_html=True)


def add_or_replace_track(track: dict):
    tracks = app_data["tracks"]
    for i, t in enumerate(tracks):
        if t.get("Title") == track["Title"]:
            tracks[i] = track
            return
    tracks.append(track)


def attach_parent_fits(tracks: list):
    """Alt mixes and cutdowns reuse their full mix's Fits line."""
    fits_by_parent = {}
    for t in tracks:
        if (t.get("Mix Type") or "") == "full":
            _, tags = gate.split_fits(t.get("Track Description", ""))
            if tags:
                fits_by_parent.setdefault(t.get("Parent Track"), tags)
    for t in tracks:
        mix = t.get("Mix Type") or ""
        if mix == "alt" or mix.startswith("cutdown"):
            body, tags = gate.split_fits(t.get("Track Description", ""))
            parent_tags = fits_by_parent.get(t.get("Parent Track"))
            if tags is None and parent_tags:
                t["Track Description"] = gate.join_fits(body, parent_tags)


def write_description(track: dict, catalog: str, **kwargs) -> bool:
    """Write one track description with the configured writer. Failures are shown, never saved as copy."""
    try:
        track["Track Description"] = eng.write_track_description(
            track, catalog, claude_api_key, lane=app_data.get("lane"), **kwargs)
        return True
    except (ClaudeError, ValueError) as exc:
        report(f"Track description failed — {track.get('Title')}", exc)
        return False


def analyse_bytes(title: str, mix_type: str, data: bytes, ext: str, catalog: str,
                  source_path: str = "", parent_track: str = "") -> dict:
    """Run the gated analysis and return the track row. A failure becomes a BLOCKED row, shown."""
    try:
        result = eng.analyze_track(data, ext, mix_type, catalog, gemini_api_key)
        track = eng.track_record(title, mix_type, result, catalog, source_path, parent_track)
    except gate.SchemaViolation as exc:
        report(f"Schema violation — {title}", exc)
        track = eng.blocked_record(title, mix_type, f"schema violation: {exc}", catalog, source_path, parent_track)
    if eng.keyword_warnings:
        st.session_state.setdefault("keyword_review", []).extend(dict(w, track=title) for w in eng.keyword_warnings)
    return track


def _reset_pipeline():
    st.session_state.pipeline = dict(_PIPE_DEFAULT)


# ── Secrets and models ─────────────────────────────────────────────────────────
def _secret(key, input_key=None):
    return _secret_value(key) or (st.session_state.get(input_key) if input_key else None)


gemini_api_key = _secret("GEMINI_API_KEY", "gemini_key_input")
claude_api_key = _secret("ANTHROPIC_API_KEY", "claude_key_input")
dropbox_token = _secret("DROPBOX_TOKEN", "dropbox_key_input")
dropbox_configured = bool(
    (_secret_value("DROPBOX_APP_KEY") and _secret_value("DROPBOX_APP_SECRET") and _secret_value("DROPBOX_REFRESH_TOKEN"))
    or dropbox_token
)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def resolve_model(slot: str, api_key: str, pinned: str, explicit: bool) -> dict:
    return model_registry.resolve(slot, api_key, pinned, explicit)


@st.cache_data(ttl=600, show_spinner=False)
def dropbox_status(configured: bool, token: str) -> dict:
    if not configured:
        return {"ok": False, "detail": "not configured"}
    try:
        account = eng.get_dropbox_client(token).users_get_current_account()
        return {"ok": True, "detail": account.name.display_name}
    except Exception as exc:
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


gemini_model = resolve_model("gemini", gemini_api_key or "", GEMINI_AUDIO_MODEL, GEMINI_PIN_EXPLICIT)
claude_model = resolve_model("claude", claude_api_key or "", CLAUDE_WRITING_MODEL, CLAUDE_PIN_EXPLICIT)
eng.gemini_model = gemini_model["id"]
eng.claude_model = claude_model["id"]


def dbx_client():
    return eng.get_dropbox_client(dropbox_token)


def model_badge(label: str, info: dict, has_key: bool) -> str:
    if not has_key:
        colour, dot, note = "#ffebee;color:#b71c1c", "🔴", "no key"
    elif info["source"] == "fallback":
        colour, dot, note = "#fff8e1;color:#8d6e00", "🟠", f"fallback pin — {info['error']}"
    else:
        colour, dot, note = "#e8f5e9;color:#1b5e20", "🟢", "pinned by secret" if info["source"] == "secret" else "latest"
    return (f'<div class="pfd-badge" style="background:{colour};">{dot} {label}: {info["id"]}</div>'
            f'<div style="font-size:0.7rem;color:#777;margin:-2px 0 4px 4px;">{note}</div>')


# ── Sidebar ────────────────────────────────────────────────────────────────────
catalog = app_data.get("catalog", "EPP")
blocked_count = eng.refresh_statuses(app_data, catalog)

with st.sidebar:
    st.markdown("### PUBLISHER FINAL DELIVERY")
    logo_map = {"redCola": "redCola logo 200x2001934x751.jpg", "SSC": "SSC 200x200 8.27.08#U202fPM.jpg",
                "EPP": "EPP 200x200.jpg"}
    logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "01_VISUAL_REFERENCES",
                             catalog, logo_map.get(catalog, ""))
    if os.path.isfile(logo_path):
        st.image(logo_path, width=160)
    st.caption(f"Catalog: **{catalog}** · Rules v{rules.version()} · writer `{rules.setting('track_writer')}`")

    st.markdown(model_badge("Analysis", gemini_model, bool(gemini_api_key))
                + model_badge("Verification", gemini_model, bool(gemini_api_key))
                + model_badge("Writing", claude_model, bool(claude_api_key)), unsafe_allow_html=True)
    _dbx_state = dropbox_status(dropbox_configured, dropbox_token or "")
    st.caption(("🟢 Dropbox: " if _dbx_state["ok"] else "🔴 Dropbox: ") + _dbx_state["detail"])

    if app_data.get("tracks"):
        if blocked_count:
            st.error(f"BLOCKED tracks in this run: {blocked_count} of {len(app_data['tracks'])}")
        else:
            st.success(f"BLOCKED tracks in this run: 0 of {len(app_data['tracks'])}")

    if st.session_state.pfd_errors:
        with st.expander(f"⚠️ Errors this session ({len(st.session_state.pfd_errors)})"):
            for _msg in reversed(st.session_state.pfd_errors):
                st.caption(_msg)
            if st.button("Clear errors", key="clear_errors"):
                st.session_state.pfd_errors = []
                st.rerun()

    pipe = st.session_state.pipeline
    if pipe["status"] == "processing":
        _total = pipe.get("total_to_analyze") or 1
        st.caption(f"🔄 Pipeline: {pipe.get('processed_count', 0)}/{_total}")
    elif pipe["status"] in ("synthesizing", "crawling"):
        st.caption(f"🔄 Pipeline: {pipe['status']}...")
    elif pipe["status"] == "error":
        st.caption("❌ Pipeline: error")

    st.divider()
    active_tab = st.radio("Navigate", TABS, index=st.session_state.active_tab_index, label_visibility="collapsed")
    if TABS.index(active_tab) != st.session_state.active_tab_index:
        st.session_state.active_tab_index = TABS.index(active_tab)
        st.rerun()

    st.divider()
    st.toggle("🧪 Writer test mode", key="writer_test",
              help="Tab 02 shows three anonymised versions per track. Tap the best; results go to Dropbox /PFD-App/tests/.")

    # ── FINAL upload (Vesna) ─────────────────────────────────────────────────
    st.markdown("**📥 Upload FINAL CSV**")
    _final_code = st.text_input("Album code", value=app_data.get("album_code", ""), key="final_album_code",
                                placeholder="e.g. EPP065")
    _final_file = st.file_uploader("FINAL CSV", type=["csv"], key="final_csv", label_visibility="collapsed")
    if st.button("Save FINAL + compare", disabled=not (_final_file and _final_code), use_container_width=True):
        try:
            _out = capture.save_final_and_diff(dbx_client(), _final_code.strip(), _final_file.getvalue())
            st.success(f"Saved {_out['final']}\n\n{_out['summary']}")
        except Exception as exc:
            report("FINAL upload failed", exc)

    # ── Keywords needing review ──────────────────────────────────────────────
    _kw_review = st.session_state.get("keyword_review", [])
    if _kw_review:
        st.markdown("---")
        st.warning(f"📝 {len(_kw_review)} keyword(s) delivered unshortened")
        with st.expander("Show them"):
            for _w in _kw_review:
                st.caption(f"**{_w.get('track', '?')}** — {_w['keyword']} ↳ {_w['reason']}")
        if st.button("Mark reviewed", key="clear_kw_review", use_container_width=True):
            st.session_state.keyword_review = []
            st.rerun()

    # ── Learning system ──────────────────────────────────────────────────────
    if dropbox_configured:
        with st.expander("🧠 Learning system"):
            _logged = feedback.count_logged_albums(dropbox_token)
            st.caption(f"{_logged} album(s) in the redo log")
            if _logged >= feedback.LOG_THRESHOLD and st.button("Run revision pass", key="revision_pass"):
                try:
                    _rev_log = feedback.load_edit_log(dropbox_token)
                    with st.spinner("Analysing feedback patterns..."):
                        _rev = eng.call_claude(rules.system_instruction(catalog),
                                               feedback.build_revision_prompt(_rev_log, catalog),
                                               claude_api_key, max_tokens=4096)
                    st.text_area("Revision pass", _rev, height=300, key="revision_results")
                    _ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M")
                    eng.upload_bytes_to_dropbox(dropbox_token, _rev.encode("utf-8"), f"/PFD-App/revision-pass-{_ts}.txt")
                    st.caption("✓ Saved to Dropbox /PFD-App/")
                except Exception as exc:
                    report("Revision pass failed", exc)

    # ── Model pins ───────────────────────────────────────────────────────────
    with st.expander("🤖 Model check"):
        if st.button("Re-check models now", key="model_check", use_container_width=True):
            resolve_model.clear()
            st.session_state.model_reports = {
                "gemini": model_registry.check_gemini(eng.gemini_model, gemini_api_key),
                "claude": model_registry.check_claude(eng.claude_model, claude_api_key),
            }
            st.rerun()
        for _label, _key in (("Gemini", "gemini"), ("Claude", "claude")):
            _rep = (st.session_state.get("model_reports") or {}).get(_key)
            if _rep:
                st.caption(model_registry.summarize(_rep, _label))
        st.caption("The app runs the newest Opus and newest Pro. A GEMINI_AUDIO_MODEL or "
                   "CLAUDE_WRITING_MODEL secret locks a model instead.")

    # ── Persistence ──────────────────────────────────────────────────────────
    if dropbox_configured:
        st.divider()
        _ls = st.session_state.get("last_auto_save", 0.0)
        if _ls:
            _el = int(time.time() - _ls)
            st.caption(f"💾 Last saved: {'just now' if _el < 60 else f'{_el // 60} min ago'}")
        _c1, _c2 = st.columns(2)
        with _c1:
            if st.button("💾 Save", disabled=not app_data.get("tracks"), use_container_width=True):
                if save_progress(dropbox_token, app_data, st.session_state.pipeline,
                                 album_desc_iterations=st.session_state.album_desc_iterations):
                    st.toast("✓ Saved to Dropbox")
        with _c2:
            if st.button("📂 Restore", use_container_width=True):
                st.session_state["_saved_sessions"] = list_sessions(dropbox_token)
        for _i, _s in enumerate(st.session_state.get("_saved_sessions") or []):
            st.markdown(f"**{_s['display']}**")
            st.caption(f"{_s['stage_summary']} · {(_s.get('save_time') or '')[:16].replace('T', ' ')}")
            if st.button("Restore this session", key=f"restore_{_i}"):
                if _s.get("app_data"):
                    st.session_state.app_data = _s["app_data"]
                st.session_state.album_desc_iterations = _s.get("album_desc_iterations") or {}
                _meta = _s.get("pipeline_meta", {})
                st.session_state.pipeline.update({
                    "album_name": _s.get("album_name", ""), "catalog": _s.get("catalog", ""),
                    "status": "done" if _s.get("stages", {}).get("ingest") else "idle",
                    "processed_count": _meta.get("processed_count", 0),
                    "total_to_analyze": _meta.get("total_to_analyze", 0),
                    "album_path": _meta.get("album_path", ""),
                })
                st.session_state.active_tab_index = _s.get("furthest_tab", 1)
                st.session_state.pop("_saved_sessions", None)
                st.rerun()

    st.divider()
    if st.button("🔄 Reset Session (clears everything)", use_container_width=True, key="reset_session_btn"):
        for _k in [k for k in st.session_state if k != "engine"]:
            del st.session_state[_k]
        st.rerun()

    with st.expander("⚙️ Configuration"):
        if not _secret_value("GEMINI_API_KEY"):
            st.text_input("Gemini API Key", type="password", key="gemini_key_input")
        if not _secret_value("ANTHROPIC_API_KEY"):
            st.text_input("Claude API Key", type="password", key="claude_key_input")
        if not dropbox_configured:
            st.text_input("Dropbox access token (temporary)", type="password", key="dropbox_key_input")
        st.caption("Keys set in Streamlit secrets are used automatically.")

active_tab_index = st.session_state.active_tab_index


def _auto_save(label: str = ""):
    if dropbox_configured and app_data.get("tracks"):
        save_progress(dropbox_token, app_data, st.session_state.pipeline,
                      album_desc_iterations=st.session_state.album_desc_iterations)
        st.session_state.last_auto_save = time.time()


# ── Auto-restore once, auto-save every 3 minutes ───────────────────────────────
if dropbox_configured and not st.session_state._auto_restored and not app_data.get("tracks"):
    st.session_state._auto_restored = True
    try:
        _recent = list_sessions(dropbox_token, max_sessions=1)
        if _recent and _recent[0].get("app_data"):
            _rs = _recent[0]
            st.session_state.app_data = _rs["app_data"]
            st.session_state.album_desc_iterations = _rs.get("album_desc_iterations") or {}
            _meta = _rs.get("pipeline_meta", {})
            st.session_state.pipeline.update({
                "album_name": _rs.get("album_name", ""), "catalog": _rs.get("catalog", ""),
                "status": "done" if _rs.get("stages", {}).get("ingest") else "idle",
                "processed_count": _meta.get("processed_count", 0),
                "total_to_analyze": _meta.get("total_to_analyze", 0),
                "album_path": _meta.get("album_path", ""),
            })
            st.session_state.active_tab_index = _rs.get("furthest_tab", 1)
            st.toast("✅ Session restored")
            st.rerun()
    except Exception as exc:
        report("Auto-restore of the last session failed", exc)

if dropbox_configured and app_data.get("tracks") and time.time() - st.session_state.last_auto_save > 180:
    _auto_save("3-min auto-save")


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE AUTO-ADVANCE — one batch per rerun, regardless of the active tab
# ══════════════════════════════════════════════════════════════════════════════
if gemini_api_key and dropbox_configured:
    pipe = st.session_state.pipeline

    if pipe["status"] == "processing" and not pipe["queue"]:
        pipe["status"] = "synthesizing"
        st.rerun()

    if pipe["status"] == "processing" and pipe["queue"]:
        batch = pipe["queue"][0]
        pipeline_catalog = pipe["catalog"]
        for entry in batch:
            pipe["current_file"] = entry.display_name
            mix = "sound_design" if entry.category == "sound_design" else entry.mix_type
            try:
                data = eng.download_bytes_from_dropbox(dropbox_token, entry.dropbox_path)
                track = analyse_bytes(entry.display_name, mix, data, os.path.splitext(entry.dropbox_path)[1],
                                      pipeline_catalog, entry.dropbox_path, entry.parent_track)
                add_or_replace_track(track)
                pipe["log"].append(f"{'✓' if track['PFD_Status'] == gate.PASSED else '⛔'} {entry.display_name} "
                                   f"[{mix}] {track['PFD_Status']} {track.get('Duration', '')}")
            except Exception as exc:
                report(f"Analysis failed — {entry.display_name}", exc)
                add_or_replace_track(eng.blocked_record(entry.display_name, mix,
                                                        f"analysis failed: {type(exc).__name__}: {exc}",
                                                        pipeline_catalog, entry.dropbox_path, entry.parent_track))
                pipe["log"].append(f"⛔ {entry.display_name}: {str(exc)[:100]}")
                if is_quota_error(exc):
                    pipe["status"] = "error"
                    pipe["error"] = (f"Gemini quota/billing error on '{entry.display_name}': {exc}\n"
                                     "Top up Gemini API credits and restart the pipeline.")
                    send_ntfy("⚠️ PFD — Gemini quota exhausted",
                              f"Pipeline stopped at '{entry.display_name}'. "
                              f"{pipe['processed_count']}/{pipe['total_to_analyze']} files done.", priority="urgent")
                    break

        if pipe["status"] != "error":
            pipe["queue"].pop(0)
            pipe["processed_count"] += len(batch)
            pipe["heartbeat_count"] += 1
            if not pipe["queue"]:
                pipe["status"] = "synthesizing"
            if dropbox_configured:
                save_progress(dropbox_token, app_data, pipe)
            st.rerun()

    elif pipe["status"] == "synthesizing":
        pipeline_catalog = pipe["catalog"]
        if claude_api_key and not st.session_state.get("writer_test"):
            for track in app_data["tracks"]:
                if track.get("analysis") and not track.get("Track Description"):
                    write_description(track, pipeline_catalog)
        attach_parent_fits(app_data["tracks"])
        blocked = eng.refresh_statuses(app_data, pipeline_catalog)
        pipe["status"] = "done"
        if dropbox_configured:
            save_progress(dropbox_token, app_data, pipe)
        send_ntfy("✅ PFD Pipeline — complete",
                  f"{pipe.get('album_name', 'Album')} ({pipe.get('catalog', '')}): "
                  f"{pipe['processed_count']} files analysed, {len(app_data['tracks'])} rows, "
                  f"{blocked} BLOCKED. Open the app to review.", priority="high")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 00 · HOME
# ══════════════════════════════════════════════════════════════════════════════
if active_tab_index == 0:
    st.markdown("<h1 style='color:#cc0000;font-size:2.2rem;font-weight:800;'>PUBLISHER FINAL DELIVERY</h1>",
                unsafe_allow_html=True)
    st.caption(f"v3 · Rules v{rules.version()}")
    st.divider()
    for num, name, desc in [
        ("01", "Ingest Audio", "Paste a Dropbox folder link. Every track gets a real duration, timestamped events, an ending type and a second listen. PASSED or BLOCKED."),
        ("02", "Track Descriptions", "Written under PFD_RULES.md. Fix only what is wrong."),
        ("03", "Lane & Album Description", "EPP: confirm the lane. Then the one-sentence album description."),
        ("04", "Album Name", "Five candidates that pass the name rules."),
        ("05", "Cover Art Prompts", "Four MidJourney prompts. No hands, faces or figures."),
        ("06", "MailChimp Intro", "40–70 words, company voice."),
        ("07", "Fix Existing Copy", "Paste any copy; Claude rewrites it under the rules."),
        ("08", "Export", "One ZIP. The DRAFT is saved to Dropbox automatically."),
    ]:
        st.markdown(f"`{num}` **{name}** — {desc}")
    next_button("Start → 01 · Ingest Audio")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 01 · INGEST AUDIO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 1:
    st.title("01 · INGEST AUDIO")
    catalog_choice = st.selectbox("Active Catalog", CATALOGS,
                                  index=CATALOGS.index(app_data.get("catalog", "EPP")))
    if catalog_choice != app_data.get("catalog"):
        app_data["catalog"] = catalog_choice
        st.rerun()
    catalog = app_data["catalog"]
    st.divider()

    mode = st.radio("Input mode", ["🔗 Dropbox folder link", "📁 Upload files"], horizontal=True)

    if mode == "🔗 Dropbox folder link":
        if not dropbox_configured:
            st.error("Dropbox is not configured. Add DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN to secrets.")
        elif not gemini_api_key:
            st.error("Gemini API key required. Add GEMINI_API_KEY to secrets.")
        else:
            pipe = st.session_state.pipeline

            if pipe["status"] == "idle":
                shared_link = st.text_input("Dropbox shared link", placeholder="https://www.dropbox.com/scl/fo/...",
                                            key="pipeline_link_input")
                if shared_link.strip():
                    pipe["shared_link"] = shared_link.strip()
                    pipe["status"] = "crawling"
                    st.rerun()

            elif pipe["status"] == "crawling":
                with st.spinner("Resolving link and scanning the folder..."):
                    try:
                        dbx = dbx_client()
                        album_path = resolve_shared_link(dbx, pipe["shared_link"])
                        if os.path.splitext(album_path)[1].lower() in (".mp3", ".wav", ".aif", ".aiff", ".flac"):
                            raise ValueError(f"This link points to a single file ({os.path.basename(album_path)}), "
                                             "not a folder. Use 📁 Upload files for a single file.")
                        pipe["album_path"] = album_path
                        detected = detect_catalog_from_path(album_path)
                        pipe["catalog"] = detected if detected != "unknown" else catalog
                        app_data["catalog"] = pipe["catalog"]
                        if not is_quality_checked(album_path):
                            pipe["log"].append("⚠️ Link is not inside a Quality Checked folder.")

                        crawl = crawl_album_folder(dbx, album_path, pipe["catalog"])
                        pipe["crawl_log"] = crawl.log
                        pipe["album_name"] = crawl.album_name
                        app_data.setdefault("album_code", capture.detect_album_code(album_path, crawl.album_name))

                        for entry in crawl.auto_described:
                            desc = (generate_alt_description(entry.parent_track, entry.notes)
                                    if entry.category == "alt_mix"
                                    else generate_cutdown_description(entry.parent_track, entry.notes))
                            add_or_replace_track({
                                "Title": entry.display_name, "Mix Type": entry.mix_type,
                                "Parent Track": entry.parent_track, "Source Path": entry.dropbox_path,
                                "Track Description": desc, "Keywords": "",
                            })

                        # A folder with loose audio and no track subfolders is analysed file by file.
                        analyzable = crawl.analyzable
                        pipe["queue"] = make_batches(analyzable)
                        pipe["total_to_analyze"] = len(analyzable)
                        pipe["processed_count"] = 0
                        pipe["log"] += [f"Catalog: {pipe['catalog']}", f"Album: {crawl.album_name}",
                                        crawl.summary() or "no analysable audio found", "─" * 40]
                        pipe["status"] = "processing"
                    except Exception as exc:
                        report("Dropbox folder scan failed", exc)
                        pipe["status"] = "error"
                        pipe["error"] = f"{type(exc).__name__}: {exc}"
                st.rerun()

            elif pipe["status"] in ("processing", "synthesizing"):
                total, done = pipe["total_to_analyze"], pipe["processed_count"]
                st.markdown(f"**{pipe.get('album_name', 'Album')}** · {pipe.get('catalog', '')} · {done}/{total} files")
                st.progress(done / total if total else 0.0)
                if pipe["status"] == "processing" and pipe.get("current_file"):
                    st.caption(f"Listening: {pipe['current_file']}")
                elif pipe["status"] == "synthesizing":
                    st.info("Analysis complete — writing track descriptions...")
                st.markdown(f'<div class="pipeline-log">{chr(10).join(pipe["log"][-30:])}</div>', unsafe_allow_html=True)

            elif pipe["status"] == "done":
                st.success(f"✅ Pipeline complete — {pipe['processed_count']} files analysed.")
                c1, c2 = st.columns(2)
                if c1.button("→ Track Descriptions (Tab 02)", type="primary"):
                    go_to_tab(2)
                if c2.button("Run new album"):
                    _reset_pipeline()
                    st.rerun()
                with st.expander("Processing log"):
                    st.markdown(f'<div class="pipeline-log">{chr(10).join(pipe["log"])}</div>', unsafe_allow_html=True)

            elif pipe["status"] == "error":
                st.error(f"❌ Pipeline error:\n\n{pipe.get('error', 'Unknown error')}")
                if st.button("Reset pipeline"):
                    _reset_pipeline()
                    st.rerun()

    else:
        if not gemini_api_key:
            st.error("Gemini API key required. Add GEMINI_API_KEY to secrets.")
        else:
            uploaded_files = st.file_uploader("Audio files", type=["mp3", "wav", "aif", "aiff", "flac"],
                                              accept_multiple_files=True)
            if st.button("Analyse", type="primary", disabled=not uploaded_files):
                progress = st.progress(0.0)
                for idx, up in enumerate(uploaded_files):
                    title, ext = os.path.splitext(up.name)
                    mix = detect_mix_type(title)
                    with st.spinner(f"Listening to file {idx + 1} of {len(uploaded_files)}..."):
                        try:
                            add_or_replace_track(analyse_bytes(title, mix, up.getvalue(), ext, catalog,
                                                               parent_track=base_title(title)))
                        except Exception as exc:
                            report(f"Analysis failed — {title}", exc)
                            add_or_replace_track(eng.blocked_record(title, mix, f"analysis failed: {type(exc).__name__}: {exc}",
                                                                    catalog, parent_track=base_title(title)))
                    progress.progress((idx + 1) / len(uploaded_files))
                eng.refresh_statuses(app_data, catalog)
                _auto_save("manual analysis")
                st.rerun()

    # ── Track status table ─────────────────────────────────────────────────────
    st.divider()
    st.subheader("Tracks")
    tracks = app_data["tracks"]
    if tracks:
        eng.refresh_statuses(app_data, catalog)
        status_filter = st.radio("Show", ["All", gate.PASSED, gate.BLOCKED], horizontal=True, key="status_filter")
        rows = [{
            "Status": t.get("PFD_Status", gate.BLOCKED),
            "Title": t.get("Title", ""),
            "Mix": t.get("Mix Type", ""),
            "Duration": t.get("Duration", ""),
            "Ending": t.get("Ending Type", ""),
            "Events": t.get("Events", ""),
            "Block reasons": "; ".join(t.get("PFD_Block_Reasons") or []),
        } for t in tracks]
        df = pd.DataFrame(rows)
        if status_filter != "All":
            df = df[df["Status"] == status_filter]
        passed_n = sum(1 for r in rows if r["Status"] == gate.PASSED)
        st.caption(f"{len(rows)} tracks · {passed_n} PASSED · {len(rows) - passed_n} BLOCKED")
        st.dataframe(df, use_container_width=True, hide_index=True)

        blocked_tracks = [t for t in tracks if t.get("PFD_Status") != gate.PASSED]
        if blocked_tracks:
            st.markdown("**BLOCKED — listen, then re-run or add a note**")
        for i, t in enumerate(blocked_tracks):
            with st.expander(f"⛔ {t['Title']}"):
                for r in t.get("PFD_Block_Reasons") or []:
                    st.markdown(f"- {r}")
                if t.get("analysis"):
                    analysis_block(t, catalog)
                note = st.text_input("One-line human note (exported with the track; status stays BLOCKED)",
                                     value=t.get("PFD_Human_Note", ""), key=f"note_{i}_{t['Title']}")
                if note != t.get("PFD_Human_Note", ""):
                    t["PFD_Human_Note"] = note
                source = t.get("Source Path", "")
                if source and dropbox_configured and gemini_api_key and st.button("Re-run analysis", key=f"rerun_{i}"):
                    with st.spinner("Listening again..."):
                        try:
                            data = eng.download_bytes_from_dropbox(dropbox_token, source)
                            new = analyse_bytes(t["Title"], t.get("Mix Type", "full"), data,
                                                os.path.splitext(source)[1], catalog, source, t.get("Parent Track", ""))
                            add_or_replace_track(new)
                        except Exception as exc:
                            report(f"Re-run failed — {t['Title']}", exc)
                    st.rerun()
    else:
        st.info("No tracks ingested yet.")
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 02 · TRACK DESCRIPTIONS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 2:
    st.title("02 · TRACK DESCRIPTIONS")
    tracks = app_data["tracks"]
    lane = app_data.get("lane")
    if not tracks:
        st.warning("Ingest tracks in Tab 01 first.")
        next_button()
        st.stop()
    if not claude_api_key:
        st.error("Claude API key required. Add ANTHROPIC_API_KEY to secrets.")
        next_button()
        st.stop()

    writable = [t for t in tracks if t.get("analysis")]

    if st.session_state.get("writer_test"):
        # ── Blind writer test ────────────────────────────────────────────────
        st.info("🧪 Writer test: three anonymised versions per track. Tap the one you would ship.")
        wt = st.session_state.writer_test_state
        missing = [t for t in writable if t["Title"] not in wt]
        if missing:
            with st.spinner(f"Writing three versions for {len(missing)} track(s)..."):
                for t in missing:
                    order = list(WRITER_MODES)
                    random.shuffle(order)
                    wt[t["Title"]] = {"variants": eng.writer_variants(t, catalog, claude_api_key, lane),
                                      "order": order, "pick": None}
            st.rerun()

        for n, t in enumerate(writable, 1):
            entry = wt[t["Title"]]
            st.markdown(f"#### Track {n}")
            for label, mode_name in enumerate(entry["order"], 1):
                st.markdown(f"**{label}.** {entry['variants'].get(mode_name) or '_(this version failed — see errors)_'}")
            choice = st.radio(f"Best version for track {n}", ["1", "2", "3"], horizontal=True,
                              index=None if entry["pick"] is None else entry["order"].index(entry["pick"]),
                              key=f"wt_pick_{n}")
            if choice:
                entry["pick"] = entry["order"][int(choice) - 1]
            st.divider()

        picks = [wt[t["Title"]]["pick"] for t in writable if wt[t["Title"]]["pick"]]
        st.caption(f"{len(picks)} of {len(writable)} tracks picked")
        if st.button("Finish test → save to Dropbox", type="primary", disabled=not picks):
            tally = {m: picks.count(m) for m in WRITER_MODES}
            lines = [f"# Writer test — {datetime.date.today().isoformat()}", "",
                     f"Catalog: {catalog} · Album: {st.session_state.pipeline.get('album_name') or app_data.get('album_name_selected') or 'session'}"
                     f" · Rules v{rules.version()} · Claude {eng.claude_model} · Gemini {eng.gemini_model}", "",
                     "## Tally", ""] + [f"- {m}: {c}" for m, c in tally.items()] + ["", "## Picks", ""]
            for n, t in enumerate(writable, 1):
                e = wt[t["Title"]]
                lines += [f"### Track {n} — {t['Title']}", f"Picked: {e['pick'] or '(no pick)'}", ""]
                for label, m in enumerate(e["order"], 1):
                    lines.append(f"{label}. [{m}] {e['variants'].get(m, '')}")
                lines.append("")
            try:
                path = capture.write_writer_test(dbx_client(), "\n".join(lines))
                st.success(f"Saved {path} · tally {tally}")
                for t in writable:
                    e = wt[t["Title"]]
                    if e["pick"] and e["variants"].get(e["pick"]):
                        t["Track Description"] = e["variants"][e["pick"]]
                eng.refresh_statuses(app_data, catalog)
                _auto_save("writer test")
            except Exception as exc:
                report("Could not save the writer test to Dropbox", exc)
        next_button()
        st.stop()

    # ── Normal mode ───────────────────────────────────────────────────────────
    attempted = st.session_state.setdefault("_tab02_attempted", set())
    needs = [t for t in writable if not t.get("Track Description") and t["Title"] not in attempted]
    if needs:
        with st.spinner(f"Writing {len(needs)} description(s)..."):
            prog = st.progress(0.0)
            for i, t in enumerate(needs):
                attempted.add(t["Title"])
                write_description(t, catalog)
                prog.progress((i + 1) / len(needs))
        attach_parent_fits(tracks)
        eng.refresh_statuses(app_data, catalog)
        _auto_save("Tab 02 writing")
        st.rerun()

    st.caption(f"{len(tracks)} rows · writer `{rules.setting('track_writer')}` · "
               f"{sum(1 for t in tracks if t.get('Track Description'))} described · "
               f"{sum(1 for t in tracks if t.get('PFD_Status') != gate.PASSED)} BLOCKED")
    st.divider()

    groups = {}
    for t in tracks:
        groups.setdefault(t.get("Parent Track") or base_title(t["Title"]), []).append(t)
    order = {"full": 0, "sparse": 1, "sound_design": 2, "alt": 3}

    for idx_g, (song, song_tracks) in enumerate(groups.items()):
        st.markdown(f"**{song}**")
        for t in sorted(song_tracks, key=lambda x: order.get(x.get("Mix Type", ""), 9)):
            title, mix_type, desc = t["Title"], t.get("Mix Type", ""), t.get("Track Description", "")
            st.markdown(f"{status_badge(t.get('PFD_Status'))} `{mix_type.upper()}` {title}", unsafe_allow_html=True)
            for r in t.get("PFD_Block_Reasons") or []:
                st.markdown(f"<div class='pfd-warn'>⚠️ {r}</div>", unsafe_allow_html=True)
            new_desc = st.text_area(f"desc_{title}", value=desc, height=100, label_visibility="collapsed",
                                    key=f"desc_edit_{title}")
            if new_desc != desc:
                t["Track Description"] = new_desc
                eng.refresh_status(t, catalog, lane)
            if t.get("analysis"):
                c_guid, c_redo, c_save = st.columns([6, 1, 1])
                c_guid.text_input("Guidance", placeholder="Guide a redo: e.g. lead with the choir...",
                                  label_visibility="collapsed", key=f"guidance_{title}")
                if c_redo.button("↺", key=f"redo_{title}", help="Write again"):
                    guidance = st.session_state.get(f"guidance_{title}", "")
                    save_to_history(title, desc)
                    with st.spinner("Writing..."):
                        ok = write_description(t, catalog, is_redo=True, user_guidance=guidance)
                    if ok:
                        feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session",
                                                 "track_description", title,
                                                 [{"draft": desc, "guidance": guidance, "accepted": False},
                                                  {"draft": t["Track Description"], "guidance": guidance, "accepted": True}],
                                                 t["Track Description"], dropbox_token) if dropbox_configured else None
                        del st.session_state[f"guidance_{title}"]
                        _auto_save(f"redo {title}")
                        st.rerun()
                if c_save.button("💾", key=f"save_{title}", help="Log this edit"):
                    if dropbox_configured:
                        feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session",
                                                 "track_description", title,
                                                 [{"draft": desc, "guidance": "manual edit", "accepted": True}],
                                                 t["Track Description"], dropbox_token)
                    _auto_save(f"manual save {title}")
                    st.toast("Saved")
                with st.expander(f"Analysis · {title}"):
                    analysis_block(t, catalog)
                history = st.session_state.track_history.get(title, [])
                if history:
                    with st.expander(f"History ({len(history)}) · {title}"):
                        for i, old in enumerate(reversed(history)):
                            st.text(old)
                            if st.button("Restore", key=f"restore_{title}_{i}"):
                                save_to_history(title, t.get("Track Description", ""))
                                t["Track Description"] = old
                                st.rerun()
        st.markdown("<hr style='margin:0.75rem 0;border:none;border-top:1px solid #e8e8e8;'>", unsafe_allow_html=True)
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 03 · LANE & ALBUM DESCRIPTION
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 3:
    st.title("03 · LANE & ALBUM DESCRIPTION")
    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()
    tracks = app_data["tracks"]

    if rules.catalog_code(catalog) == "EPP":
        st.subheader("Lane")
        lane_list = rules.lanes()
        names = [l["name"] for l in lane_list]
        if not app_data.get("lane_proposed") and any(t.get("analysis") for t in tracks) \
                and not st.session_state.get("_lane_attempted"):
            st.session_state["_lane_attempted"] = True
            with st.spinner("Proposing a lane from the album analysis..."):
                try:
                    app_data["lane_proposed"] = eng.propose_lane(tracks, claude_api_key)
                except (ClaudeError, ValueError) as exc:
                    report("Lane proposal failed — pick one by hand", exc)
        current = app_data.get("lane") or app_data.get("lane_proposed") or names[0]
        labels = {l["name"]: f"{l['name']} ({l['status']})" for l in lane_list}
        chosen = st.selectbox("Lane (active lanes first)", names, index=names.index(current),
                              format_func=lambda n: labels[n])
        if app_data.get("lane_proposed"):
            st.caption(f"Proposed from the analysis: **{app_data['lane_proposed']}**")
        brief = next((l["brief"] for l in lane_list if l["name"] == chosen), "")
        if brief:
            st.caption(brief)
        if st.button("Confirm lane", type="primary"):
            eng.apply_lane(app_data, chosen)
            eng.refresh_statuses(app_data, catalog)
            _auto_save("lane confirmed")
            st.rerun()
        if app_data.get("lane"):
            st.success(f"Lane confirmed: **{app_data['lane']}** — first keyword and first Fits tag on every track.")
        else:
            st.warning("Lane not confirmed yet. Export lists it as an open issue.")
        st.divider()

    st.subheader("Album description")
    _iter_key = f"album_desc_iters__{st.session_state.pipeline.get('album_name') or 'session'}"
    iterations = st.session_state.album_desc_iterations.setdefault(_iter_key, [])
    descs = [t.get("Track Description", "") for t in tracks if t.get("Track Description")]
    st.caption(f"From {len(descs)} track description(s) and the catalog's last ten album descriptions.")
    if st.button("Generate album description", type="primary", disabled=not descs):
        with st.spinner("Writing..."):
            try:
                result = eng.generate_album_description(descs, catalog, claude_api_key)
                app_data["album_description"] = result
                iterations.append({"guidance": "", "description": result, "timestamp": time.strftime("%H:%M:%S")})
                _auto_save("album description")
            except ClaudeError as exc:
                report("Album description failed", exc)
        st.rerun()

    edited = st.text_area("Album Description", value=app_data.get("album_description", ""), height=110,
                          label_visibility="collapsed")
    app_data["album_description"] = edited
    if edited:
        for r in gate.album_description_reasons(edited, catalog):
            st.markdown(f"<div class='pfd-warn'>⚠️ {r}</div>", unsafe_allow_html=True)
        copy_button(edited, "album_desc")

    with st.expander("✏️ Refine with direction"):
        for i, item in enumerate(iterations):
            c1, c2 = st.columns([7, 2])
            c1.caption(f"🕐 {item['timestamp']} · {item.get('guidance') or 'initial'}")
            if c2.button("Use this", key=f"use_iter_{i}"):
                app_data["album_description"] = item["description"]
                if dropbox_configured:
                    feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session",
                                             "album_description", "",
                                             [{"draft": it["description"], "guidance": it.get("guidance", ""),
                                               "accepted": j == i} for j, it in enumerate(iterations)],
                                             item["description"], dropbox_token)
                st.rerun()
            st.text(item["description"])
        guidance = st.text_input("Your direction", key=f"album_desc_guidance_{_iter_key}")
        if st.button("Generate with direction", disabled=not descs):
            with st.spinner("Refining..."):
                try:
                    result = eng.generate_album_description_iteration(descs, catalog, iterations, guidance, claude_api_key)
                    iterations.append({"guidance": guidance, "description": result, "timestamp": time.strftime("%H:%M:%S")})
                    app_data["album_description"] = result
                    _auto_save("album description iteration")
                except ClaudeError as exc:
                    report("Album description refinement failed", exc)
            st.rerun()
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 04 · ALBUM NAME
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 4:
    st.title("04 · ALBUM NAME")
    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()
    descs = [t.get("Track Description", "") for t in app_data["tracks"] if t.get("Track Description")]
    if st.button("Generate five names", type="primary", disabled=not app_data.get("album_description")):
        with st.spinner("Generating..."):
            try:
                out = eng.generate_album_names(app_data["album_description"], catalog, claude_api_key, descs)
                app_data["album_name_candidates"] = [n["name"] for n in out["names"]]
                app_data["album_name_rationales"] = {n["name"]: n["rationale"] for n in out["names"]}
                app_data["album_names_rejected"] = out["rejected"]
                app_data["album_name"] = "\n".join(app_data["album_name_candidates"])
                _auto_save("album names")
            except ClaudeError as exc:
                report("Album names failed", exc)
        st.rerun()
    if not app_data.get("album_description"):
        st.caption("Write the album description in Tab 03 first.")

    options = app_data.get("album_name_candidates") or []
    if options:
        current = app_data.get("album_name_selected", "")
        selected = st.radio("Choose the title", options, index=options.index(current) if current in options else 0)
        if selected != current:
            app_data["album_name_selected"] = selected
            if dropbox_configured:
                feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session", "album_name",
                                         "", [{"draft": app_data["album_name"], "guidance": "", "accepted": True}],
                                         selected, dropbox_token)
            _auto_save("album name selected")
        st.caption((app_data.get("album_name_rationales") or {}).get(selected, ""))
        if len(options) < 5:
            st.warning(f"Only {len(options)} candidates passed the name rules. Generate again for more.")
        copy_button(selected, "album_name")
    rejected = app_data.get("album_names_rejected") or []
    if rejected:
        with st.expander(f"Rejected before display ({len(rejected)})"):
            for r in rejected:
                st.caption(f"{r['name']} — {'; '.join(r['reasons'])}")
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 05 · COVER ART PROMPTS
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 5:
    st.title("05 · COVER ART PROMPTS")
    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()
    album_name = app_data.get("album_name_selected", "")
    if not album_name:
        st.warning("No album name selected. Complete Tab 04 first.")
    st.caption("MidJourney stays manual. Four narrative prompts; no hands, faces or figures. Replace `[URL]` with the --sref image.")
    if st.button("Generate prompts", type="primary", disabled=not album_name):
        with st.spinner("Writing prompts..."):
            try:
                keywords = ", ".join(t.get("Keywords", "") for t in app_data["tracks"] if t.get("Keywords"))
                app_data["cover_art"] = eng.generate_cover_art_prompts(
                    album_name, app_data.get("album_description", ""), catalog, [], claude_api_key,
                    track_descriptions=[t.get("Track Description", "") for t in app_data["tracks"]],
                    keywords=keywords)
                if dropbox_configured:
                    feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session", "cover_art",
                                             "", [{"draft": app_data["cover_art"], "guidance": "", "accepted": True}],
                                             app_data["cover_art"], dropbox_token)
                _auto_save("cover art")
            except ClaudeError as exc:
                report("Cover-art prompts failed", exc)
        st.rerun()

    edited = st.text_area("MidJourney prompts", value=app_data.get("cover_art", ""), height=380,
                          label_visibility="collapsed")
    app_data["cover_art"] = edited
    if edited:
        anatomy = re.findall(r"(?<![A-Za-z])(hands?|faces?|fingers?|portrait|person|people|crowds?|man|woman|"
                             r"figures?|silhouettes? of a (?:man|woman|person)|body|bodies)(?![A-Za-z])",
                             edited, flags=re.IGNORECASE)
        if anatomy:
            st.markdown(f"<div class='pfd-warn'>⚠️ Anatomy rule: prompts mention {', '.join(sorted(set(a.lower() for a in anatomy)))}</div>",
                        unsafe_allow_html=True)
        for i, p in enumerate([p.strip() for p in edited.split("\n\n") if p.strip()]):
            copy_button(p, f"prompt_{i}", f"Copy block {i + 1}")
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 06 · MAILCHIMP INTRO
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 6:
    st.title("06 · MAILCHIMP INTRO")
    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()
    album_name = app_data.get("album_name_selected", "")
    if st.button("Write MailChimp intro", type="primary", disabled=not album_name):
        with st.spinner("Writing..."):
            try:
                app_data["mailchimp_intro"] = eng.generate_mailchimp_intro(
                    album_name, app_data.get("album_description", ""), catalog, claude_api_key,
                    track_descriptions=[t.get("Track Description", "") for t in app_data["tracks"]])
                if dropbox_configured:
                    feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session", "mailchimp",
                                             "", [{"draft": app_data["mailchimp_intro"], "guidance": "", "accepted": True}],
                                             app_data["mailchimp_intro"], dropbox_token)
                _auto_save("mailchimp")
            except ClaudeError as exc:
                report("MailChimp intro failed", exc)
        st.rerun()
    if not album_name:
        st.caption("Select an album name in Tab 04 first.")
    intro = app_data.get("mailchimp_intro", "")
    edited = st.text_area("Intro", value=intro, height=200)
    app_data["mailchimp_intro"] = edited
    if edited:
        words = len(edited.split())
        if not 40 <= words <= 70:
            st.markdown(f"<div class='pfd-warn'>⚠️ {words} words (spec: 40–70)</div>", unsafe_allow_html=True)
        if "!" in edited or re.search(r"\bexcited\b", edited, re.IGNORECASE):
            st.markdown("<div class='pfd-warn'>⚠️ No exclamation marks, no \"excited\"</div>", unsafe_allow_html=True)
        copy_button(edited, "mailchimp")
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 07 · FIX EXISTING COPY
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 7:
    st.title("07 · FIX EXISTING COPY")
    if not claude_api_key:
        st.error("Claude API key required.")
        st.stop()
    content_type = st.selectbox("Content type", ["Track Description", "Album Description", "MailChimp Intro", "Album Name", "Other"])
    bad_copy = st.text_area("Paste the copy here", height=200)
    if st.button("Rewrite under the rules", type="primary", disabled=not bad_copy):
        with st.spinner("Rewriting..."):
            try:
                st.session_state["refined_copy"] = eng.manual_refinement(bad_copy, content_type, catalog, claude_api_key)
            except ClaudeError as exc:
                report("Rewrite failed", exc)
    result = st.session_state.get("refined_copy", "")
    if result:
        st.text_area("Rewritten", value=result, height=200)
        copy_button(result, "manual_refine")

        def _log_fix(target: str):
            if dropbox_configured:
                feedback.log_interaction(catalog, st.session_state.pipeline.get("album_name") or "session",
                                         "fix_existing_copy", target,
                                         [{"draft": bad_copy, "guidance": content_type, "accepted": True}], result, dropbox_token)

        c1, c2 = st.columns(2)
        if c1.button("→ Album Description"):
            app_data["album_description"] = result
            _log_fix("album_description")
            st.success("Applied.")
        if c1.button("→ MailChimp Intro"):
            app_data["mailchimp_intro"] = result
            _log_fix("mailchimp")
            st.success("Applied.")
        if c2.button("→ Album Name"):
            app_data["album_name_selected"] = result
            _log_fix("album_name")
            st.success("Applied.")
        if content_type == "Track Description" and app_data["tracks"]:
            target = c2.selectbox("Apply to track", [t["Title"] for t in app_data["tracks"]])
            if c2.button("→ Apply to track"):
                for t in app_data["tracks"]:
                    if t["Title"] == target:
                        save_to_history(target, t.get("Track Description", ""))
                        t["Track Description"] = result
                eng.refresh_statuses(app_data, catalog)
                _log_fix(target)
                st.success(f"Applied to '{target}'.")
    next_button()


# ══════════════════════════════════════════════════════════════════════════════
# TAB 08 · EXPORT
# ══════════════════════════════════════════════════════════════════════════════
elif active_tab_index == 8:
    st.title("08 · EXPORT")
    tracks = app_data.get("tracks", [])
    passed, errors = eng.validate_data(app_data, catalog)
    blocked_n = sum(1 for t in tracks if t.get("PFD_Status") != gate.PASSED)

    c = st.columns(3)
    c[0].metric("Rows", len(tracks))
    c[1].metric("PASSED", len(tracks) - blocked_n)
    c[2].metric("BLOCKED", blocked_n)

    if passed:
        st.success("All checks clear.")
    else:
        st.warning(f"{len(errors)} open issue(s). BLOCKED rows export with their status and reasons — never as if they passed.")
        with st.expander("Open issues", expanded=blocked_n == 0):
            for e in errors:
                st.caption(e)

    album_code = st.text_input(
        "Album code", value=app_data.get("album_code") or capture.detect_album_code(
            st.session_state.pipeline.get("album_path", ""), st.session_state.pipeline.get("album_name", "")),
        placeholder="e.g. EPP065")
    app_data["album_code"] = album_code.strip()

    if not tracks:
        st.info("Nothing to export yet.")
    elif not album_code.strip():
        st.info("Enter the album code to export.")
    elif st.button("Export ZIP (saves DRAFT to Dropbox)", type="primary"):
        attach_parent_fits(tracks)
        eng.validate_data(app_data, catalog)
        with st.spinner("Building export and saving DRAFT..."):
            try:
                dbx = dbx_client()
                reference = capture.read_columns_reference(dbx)
                zip_bytes, zip_name, draft_path = capture.export_album(dbx, app_data, catalog, album_code.strip(), reference)
                st.session_state["export_zip"] = (zip_bytes, zip_name)
                st.success(f"DRAFT saved to Dropbox: `{draft_path}`"
                           + ("" if reference else " · column order: app default (no sourceaudio_columns.txt yet)"))
                send_ntfy("📦 PFD — album exported",
                          f"{os.path.basename(draft_path)} saved. {len(tracks)} rows, {blocked_n} BLOCKED.")
            except Exception as exc:
                report("DRAFT was NOT saved to Dropbox — this export is not captured", exc)
                zip_bytes, zip_name = capture.build_zip(app_data, catalog, album_code.strip())
                st.session_state["export_zip"] = (zip_bytes, zip_name)

    if st.session_state.get("export_zip"):
        zip_bytes, zip_name = st.session_state["export_zip"]
        st.download_button("Download ZIP", zip_bytes, file_name=zip_name, mime="application/zip", type="primary")
        st.caption("ZIP: one CSV (with PFD_Status and PFD_Block_Reasons) + Album_Description, Album_Names, MailChimp_Intro, Cover_Art_Prompts.")
