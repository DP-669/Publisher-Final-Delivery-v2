"""
Publisher Final Delivery — v4.

Three steps: Start → Review → Export.
- Start: pick the catalog, paste the Dropbox folder link, analyze. Every track is
  listened to (Call A), checked against its own waveform (gate.py) and written
  (Call B). Progress is saved to /PFD-App/albums/<CODE>/state.json after every track.
- Review: one table. Green = ready, amber = ready with a note, red = blocked with
  a plain-language reason and a fix panel.
- Export: one ZIP for SourceAudio; the untouched DRAFT CSV is saved to Dropbox.
Sidebar: system health only.
"""
import dataclasses
import datetime
import html
import os
import random
import re

import pandas as pd
import streamlit as st

import capture
import gate
import models as model_registry
import rules
from analysis_schema import family_label, find_observation
from dropbox_pipeline import (
    crawl_album_folder, detect_mix_type, generate_alt_description, generate_cutdown_description, is_quota_error,
    loose_audio_entries, resolve_shared_link, send_ntfy, single_file_entry,
)
from engine import (
    CLAUDE_PIN_EXPLICIT, CLAUDE_WRITING_MODEL, GEMINI_AUDIO_MODEL, GEMINI_PIN_EXPLICIT, OVERRIDE,
    SECONDS_PER_TRACK, SKIPPED, WRITER_MODES, ClaudeError, IngestionEngine, _secret_value, base_title,
    is_alt_or_cutdown, new_track_id, override_reason, remaining_uncertain, track_key,
)
from pfd_errors import report

st.set_page_config(page_title="Publisher Final Delivery", page_icon="🎵", layout="wide",
                   initial_sidebar_state="expanded")

st.markdown("""
<style>
    /* Streamlit's own header floats over the top of the page; keep the step bar clear of it. */
    .block-container { max-width: 1100px; padding-top: 5rem; }
    div[data-testid="stButton"] button[kind] p { font-size: 1rem; }
    .pfd-catalog button { min-height: 4.5rem; }
    .pfd-catalog button p { font-size: 1.15rem !important; font-weight: 600; }
    .pfd-badge { display:inline-block;border-radius:4px;padding:2px 8px;font-size:0.75rem;font-weight:700;margin:2px 0; }
    .pfd-reason { background:#fff4f4;color:#4a1010;border-left:4px solid #c62828;padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;margin:0.4rem 0; }
    .pfd-note { background:#fff8e6;color:#4a3300;border-left:4px solid #e0a100;padding:0.6rem 0.9rem;border-radius:0 6px 6px 0;margin:0.4rem 0; }
</style>
""", unsafe_allow_html=True)

CATALOGS = [("rC", "redCola"), ("SSC", "Short Story Collective"), ("EPP", "Ekonomic Propaganda")]
CATALOG_NAMES = dict(CATALOGS)
LOGOS = {"rC": ("redCola", "redCola logo 200x2001934x751.jpg"), "SSC": ("SSC", "SSC 200x200 8.27.08#U202fPM.jpg"),
         "EPP": ("EPP", "EPP 200x200.jpg")}
DOT = {gate.PASSED: "🟢", gate.PASSED_WITH_UNCERTAINTY: "🟠", gate.BLOCKED: "🔴", SKIPPED: "⚪", OVERRIDE: "🔵"}
LABEL = {gate.PASSED: "Ready", gate.PASSED_WITH_UNCERTAINTY: "Ready with note", gate.BLOCKED: "Blocked",
         SKIPPED: "Skipped", OVERRIDE: "Override"}
AUDIO_FORMATS = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".aif": "audio/aiff", ".aiff": "audio/aiff",
                 ".flac": "audio/flac"}

# ── Session state ──────────────────────────────────────────────────────────────
ss = st.session_state
if "engine" not in ss:
    ss.engine = IngestionEngine()
eng: IngestionEngine = ss.engine
for _k, _v in {"step": "start", "album": None, "running": False, "dirty": False, "confirm_reset": False,
               "catalog_choice": None, "selected": None, "editor_nonce": 0, "folder_checks": {},
               "fix_mode": "", "export_result": None, "field_ver": 0, "audio_cache": {},
               "uploads": {}, "results": {}}.items():
    if _k not in ss:
        ss[_k] = _v

# ── Secrets, models, Dropbox ───────────────────────────────────────────────────
gemini_api_key = _secret_value("GEMINI_API_KEY")
claude_api_key = _secret_value("ANTHROPIC_API_KEY")
dropbox_token = _secret_value("DROPBOX_TOKEN")
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


# ── Album helpers ──────────────────────────────────────────────────────────────
def album_catalog() -> str:
    return (ss.album or {}).get("catalog") or ss.catalog_choice or "rC"


def album_lane():
    album = ss.album or {}
    return album.get("lane") if album.get("catalog") == "EPP" else None


def find_track(track_id: str):
    return next((t for t in (ss.album or {}).get("tracks", []) if track_key(t) == track_id), None)


def put_track(track: dict):
    """
    Store a row under its stable id, in the album and in the session's own result
    store. ss.results is what makes a computed result survive anything the page
    does: a rerender, a filter, a step change, or an album reloaded from Dropbox.
    """
    key = track_key(track)
    tracks = ss.album["tracks"]
    for i, t in enumerate(tracks):
        if track_key(t) == key:
            tracks[i] = track
            break
    else:
        tracks.append(track)
    ss.results[key] = track


def restore_results(album: dict):
    """Put back anything this session already computed. A result is never lost to a blank row."""
    for i, t in enumerate(album.get("tracks") or []):
        cached = ss.results.get(track_key(t))
        if cached is t:
            continue
        if cached and (cached.get("analysis") or cached.get("Track Description")) and not t.get("analysis"):
            album["tracks"][i] = cached
        else:
            ss.results[track_key(t)] = t


def save_album(mark_dirty: bool = True):
    """state.json in Dropbox. A failed save is shown; the session keeps the work."""
    album = ss.album
    if not album:
        return
    album["updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    if mark_dirty:
        ss.dirty = True
    if not (dropbox_configured and album.get("album_code")):
        return
    try:
        capture.save_state(dbx_client(), album["album_code"], album)
        recent_albums.clear()
    except Exception as exc:
        report("Progress was not saved to Dropbox", exc)


def reset_album():
    for key in ("album", "selected", "export_result"):
        ss[key] = None
    ss.update(step="start", running=False, dirty=False, confirm_reset=False, fix_mode="", folder_checks={},
              catalog_choice=None, uploads={}, audio_cache={}, results={})
    for key in ("link_input", "code_input", "upload_code", "upload_input"):
        ss.pop(key, None)


def track_bytes(track: dict) -> bytes:
    """The audio behind a track: an uploaded file from this session, or its Dropbox path."""
    key = track.get("Upload Key")
    if key:
        data = ss.uploads.get(key)
        if data is None:
            raise RuntimeError("That file was uploaded in an earlier session. Upload it again to re-run this track.")
        return data
    return eng.download_bytes_from_dropbox(dropbox_token, track["Source Path"])


def track_extension(track: dict) -> str:
    name = track.get("Upload Key") or track.get("Source Path", "")
    return os.path.splitext(name)[1] or ".mp3"


def track_audio(track: dict):
    if track.get("Upload Key"):
        return ss.uploads.get(track["Upload Key"])
    path = track.get("Source Path", "")
    if not path:
        return None
    if path not in ss.audio_cache:
        ss.audio_cache = {path: eng.download_bytes_from_dropbox(dropbox_token, path)}  # keep one file in memory
    return ss.audio_cache[path]


def can_listen_again(track: dict) -> bool:
    if is_alt_or_cutdown(track) or not gemini_api_key:
        return False
    if track.get("Upload Key"):
        return track["Upload Key"] in ss.uploads
    return bool(track.get("Source Path") and dropbox_configured)


def mix_for(entry: dict) -> str:
    return "sound_design" if entry.get("category") == "sound_design" else entry.get("mix_type", "full")


@st.cache_data(ttl=120, show_spinner=False)
def recent_albums(configured: bool) -> list:
    if not configured:
        return []
    return capture.list_recent_albums(dbx_client())


def folder_check(link: str, catalog: str) -> dict:
    """
    Resolve a Dropbox link once. Three shapes, all analysed the same way:
    an album folder with track subfolders, a folder of loose audio files, or one file.
    """
    if link in ss.folder_checks:
        return ss.folder_checks[link]
    out = {"ok": False, "error": "", "kind": "", "analyzable": [], "auto": []}
    try:
        dbx = dbx_client()
        path = resolve_shared_link(dbx, link)
        if os.path.splitext(path)[1].lower() in AUDIO_FORMATS:
            entry = single_file_entry(dbx, path)
            folder = os.path.dirname(path)
            out.update(ok=True, kind="file", album_path=folder, folder_name=os.path.basename(folder),
                       code=capture.detect_album_code(entry.display_name, path),
                       analyzable=[dataclasses.asdict(entry)])
        else:
            crawl = crawl_album_folder(dbx, path, catalog)
            entries = [dataclasses.asdict(e) for e in crawl.analyzable]
            auto = [dataclasses.asdict(e) for e in crawl.auto_described]
            kind = "album"
            if not entries and not auto:  # loose files, no track subfolders
                entries = [dataclasses.asdict(e) for e in loose_audio_entries(dbx, path)]
                kind = "files"
            out.update(ok=True, kind=kind, album_path=path, folder_name=crawl.album_name,
                       code=capture.detect_album_code(crawl.album_name, path),
                       analyzable=entries, auto=auto)
    except Exception as exc:
        report("Could not read that Dropbox link", exc, show=False)
        out["error"] = f"{type(exc).__name__}: {exc}"
    ss.folder_checks[link] = out
    return out


def upload_entries(files) -> tuple:
    """(entries, {name: bytes}) for manually uploaded audio."""
    entries, blobs = [], {}
    for f in files or []:
        title = os.path.splitext(f.name)[0]
        blobs[f.name] = f.getvalue()
        entries.append({"display_name": title, "dropbox_path": "", "file_id": "", "size": len(blobs[f.name]),
                        "category": "full_mix", "parent_track": base_title(title),
                        "mix_type": detect_mix_type(f.name), "notes": "", "upload_key": f.name,
                        "track_id": new_track_id()})
    return entries, blobs


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — system health only
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("### Publisher Final Delivery")
    st.caption(f"Rules v{rules.version()}")
    st.markdown(model_badge("Listening", gemini_model, bool(gemini_api_key))
                + model_badge("Writing", gemini_model, bool(gemini_api_key))
                + model_badge("Checking", claude_model, bool(claude_api_key)), unsafe_allow_html=True)
    _dbx = dropbox_status(dropbox_configured, dropbox_token or "")
    st.caption(("🟢 Dropbox: " if _dbx["ok"] else "🔴 Dropbox: ") + _dbx["detail"])
    if any(t.get("call_a_mode") == "prompt-fallback" for t in (ss.album or {}).get("tracks", [])):
        st.warning("Schema rejected by Gemini — ran in prompt mode; check DECISIONS.md.")
    with st.expander("Settings"):
        st.toggle("Compare writing styles", key="compare_styles",
                  help="In Review, write three versions of a track's description and pick the best.")


# ══════════════════════════════════════════════════════════════════════════════
# HEADER — step bar and New album
# ══════════════════════════════════════════════════════════════════════════════
album = ss.album
has_tracks = bool(album and album.get("tracks"))
step_enabled = {"start": True, "review": has_tracks and not ss.running, "export": has_tracks and not ss.running}
if not step_enabled.get(ss.step):
    ss.step = "start"

head, new_col = st.columns([5, 1], vertical_alignment="center")
with head:
    steps = st.columns(3)
    for col, (key, label) in zip(steps, (("start", "1 · Start"), ("review", "2 · Review"), ("export", "3 · Export"))):
        if col.button(label, key=f"step_{key}", use_container_width=True, disabled=not step_enabled[key],
                      type="primary" if ss.step == key else "secondary"):
            ss.step = key
            ss.selected = None
            st.rerun()
with new_col:
    if st.button("New album", key="new_album", use_container_width=True):
        if album and ss.dirty:
            ss.confirm_reset = True
        else:
            reset_album()
        st.rerun()

if ss.confirm_reset:
    c_msg, c_yes, c_no = st.columns([4, 1, 1], vertical_alignment="center")
    c_msg.warning("This album has changes that haven't been exported. Start a new album anyway?")
    if c_yes.button("Yes, start over", key="confirm_reset_yes"):
        reset_album()
        st.rerun()
    if c_no.button("No", key="confirm_reset_no"):
        ss.confirm_reset = False
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# START
# ══════════════════════════════════════════════════════════════════════════════
def render_progress():
    album = ss.album
    catalog = album["catalog"]
    total = album.get("total") or len(album["pending"])
    header = st.empty()
    bar = st.progress(0.0)
    if st.button("Stop", key="stop_run"):
        ss.running = False
        album["run_status"] = "paused"
        save_album()
        st.rerun()
    rows = st.container()
    with rows:
        for t in album["tracks"]:
            if not is_alt_or_cutdown(t):
                st.markdown(f"{DOT.get(t.get('PFD_Status'), '⚪')} **{t['Title']}** · {t.get('Duration', '')} · "
                            f"{LABEL.get(t.get('PFD_Status'), '')}")

    while album["pending"]:
        entry = album["pending"][0]
        done = total - len(album["pending"])
        header.markdown(f"#### Track {done + 1} of {total} — listening…\n{entry['display_name']}")
        bar.progress(done / total if total else 0.0)
        mix = mix_for(entry)
        upload_key = entry.get("upload_key", "")
        ext = os.path.splitext(upload_key or entry["dropbox_path"])[1] or ".mp3"
        try:
            if upload_key:
                data = ss.uploads.get(upload_key)
                if data is None:
                    raise RuntimeError("that file was uploaded in an earlier session — upload it again")
            else:
                data = eng.download_bytes_from_dropbox(dropbox_token, entry["dropbox_path"])
            track = eng.process_track(entry["display_name"], mix, data, ext, catalog, gemini_api_key, claude_api_key,
                                      album_lane(), entry["dropbox_path"], entry["parent_track"],
                                      track_id=entry.get("track_id", ""))
            track["Upload Key"] = upload_key
        except Exception as exc:
            report(f"Analysis failed — {entry['display_name']}", exc)
            if is_quota_error(exc):
                ss.running = False
                album["run_status"] = "paused"
                save_album()
                send_ntfy("⚠️ PFD — Gemini quota exhausted",
                          f"{album['album_code']}: stopped at track {done + 1} of {total} "
                          f"('{entry['display_name']}'). Top up Gemini credits, then Resume.", priority="urgent")
                st.rerun()
            track = eng.blocked_record(entry["display_name"], mix, gate.failure("API", error=str(exc)[:300]),
                                       catalog, entry["dropbox_path"], entry["parent_track"],
                                       track_id=entry.get("track_id", ""))
            track["Upload Key"] = upload_key
        put_track(track)
        album["pending"].pop(0)
        eng.refresh_statuses(album, catalog)
        save_album()
        with rows:
            st.markdown(f"{DOT.get(track.get('PFD_Status'), '⚪')} **{track['Title']}** · {track.get('Duration', '')} · "
                        f"{LABEL.get(track.get('PFD_Status'), '')}")

    counts = eng.status_counts(album["tracks"])
    album["run_status"] = "review"
    ss.running = False
    save_album()
    send_ntfy("✅ PFD — album analysed",
              f"{album['album_code']} ({CATALOG_NAMES.get(catalog, catalog)}): {total} files listened to. "
              f"{counts['ready']} ready, {counts['uncertain']} ready with a note, {counts['blocked']} blocked. "
              "Open the app to review.", priority="high")
    ss.step = "review"
    st.rerun()


def start_album(catalog: str, code: str, entries: list, auto: list, check: dict, uploads: dict):
    """A folder, a handful of loose files, one file or an upload — all start a run the same way."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    ss.uploads = dict(uploads)
    ss.album = {
        "album_code": code, "catalog": catalog, "shared_link": ss.get("link_input", ""),
        "album_path": check.get("album_path", ""),
        "album_folder_name": check.get("folder_name") or code, "created": now, "updated": now,
        "run_status": "analyzing", "input": "upload" if uploads else (check.get("kind") or "album"),
        "pending": list(entries), "total": len(entries), "tracks": [],
        "lane": None, "lane_proposed": None, "album_description": "", "album_name_candidates": [],
        "album_name_rationales": {}, "album_name_selected": "", "mailchimp_intro": "", "cover_art": "",
        "writer_test": {}, "exported_at": None,
    }
    ss.results = {}
    for e in auto:
        desc = (generate_alt_description(e["parent_track"], e["notes"]) if e["category"] == "alt_mix"
                else generate_cutdown_description(e["parent_track"], e["notes"]))
        put_track({"track_id": new_track_id(), "Title": e["display_name"], "Mix Type": e["mix_type"],
                   "Parent Track": e["parent_track"], "Source Path": e["dropbox_path"],
                   "Track Description": desc, "Keywords": ""})
    ss.running = True
    ss.export_result = None
    save_album()


def open_album(code: str):
    try:
        state = capture.load_state(dbx_client(), code)
    except Exception as exc:
        report(f"Could not open {code}", exc)
        return
    state.setdefault("tracks", [])
    state.setdefault("pending", [])
    state.setdefault("writer_test", {})
    ss.album = state
    restore_results(state)
    ss.update(dirty=False, selected=None, export_result=None, catalog_choice=state.get("catalog"))
    ss.step = "review" if state["tracks"] and not state["pending"] else "start"
    st.rerun()


def render_recent():
    st.markdown("#### Recent albums")
    if not dropbox_configured:
        st.caption("Dropbox is not configured.")
        return
    try:
        rows = recent_albums(dropbox_configured)
    except Exception as exc:
        report("Could not list recent albums", exc)
        return
    if not rows:
        st.caption("No albums yet.")
        return
    for r in rows:
        c = st.columns([1.2, 3, 1.3, 1.3, 1, 2], vertical_alignment="center")
        c[0].markdown(f"**{r['code']}**")
        c[1].write(r["name"] or "—")
        c[2].write(r["date"])
        c[3].write("Exported" if r["exported"] else (r["status"] or "").capitalize())
        if c[4].button("Open", key=f"open_{r['code']}"):
            open_album(r["code"])
        if r["exported"]:
            with c[5].popover("Upload Vesna's final"):
                final = st.file_uploader("Vesna's FINAL CSV", type=["csv"], key=f"final_{r['code']}")
                if st.button("Save and compare", key=f"final_save_{r['code']}", disabled=not final):
                    try:
                        out = capture.save_final_and_diff(dbx_client(), r["code"], final.getvalue())
                        st.success(f"Saved. {out['summary']}")
                    except Exception as exc:
                        report("Vesna's final was not saved", exc)


def render_start():
    if ss.running and ss.album:
        render_progress()
        return

    album = ss.album
    if album and album.get("pending"):
        total = album.get("total") or 0
        done = total - len(album["pending"])
        st.info(f"{album['album_code']} is paused at track {done} of {total}.")
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button("Resume", type="primary", key="resume_run", disabled=not gemini_api_key):
            ss.running = True
            album["run_status"] = "analyzing"
            st.rerun()
        if c2.button("Review what's done", key="review_partial", disabled=not album.get("tracks")):
            ss.step = "review"
            st.rerun()
        st.divider()

    st.markdown("#### Catalog")
    st.markdown('<div class="pfd-catalog">', unsafe_allow_html=True)
    cols = st.columns(3)
    root = os.path.dirname(os.path.abspath(__file__))
    for col, (code, name) in zip(cols, CATALOGS):
        with col:
            folder, filename = LOGOS[code]
            logo = os.path.join(root, "01_VISUAL_REFERENCES", folder, filename)
            if os.path.isfile(logo):
                st.image(logo, width=90)
            if st.button(name, key=f"catalog_{code}", use_container_width=True,
                         type="primary" if ss.catalog_choice == code else "secondary"):
                ss.catalog_choice = code
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("#### Audio")
    source = st.radio("Where the audio is", ["Dropbox link", "Upload files"], horizontal=True,
                      key="input_mode", label_visibility="collapsed")

    check, entries, auto, uploads, code, problem, has_input = {}, [], [], {}, "", "", False
    if source == "Dropbox link":
        c_link, c_code = st.columns([5, 1])
        link = c_link.text_input("Paste a Dropbox link — an album folder, a folder of files, or a single file",
                                 key="link_input", placeholder="https://www.dropbox.com/scl/fo/…").strip()
        has_input = bool(link)
        if link and not dropbox_configured:
            problem = "Dropbox is not configured, so the link can't be read."
        elif link:
            with st.spinner("Checking the link…"):
                check = folder_check(link, ss.catalog_choice or "")
            if not check.get("ok"):
                problem = f"That link couldn't be opened. {check.get('error', '')}"
            else:
                entries, auto = check["analyzable"], check["auto"]
                if check["code"]:
                    code = check["code"]
                    c_code.text_input("Album code", value=code, disabled=True, key=f"code_shown_{code}")
                else:
                    code = c_code.text_input("Album code", key="code_input", placeholder="SSC042").strip().upper()
    else:
        files = st.file_uploader("Audio files", type=sorted(e.lstrip(".") for e in AUDIO_FORMATS),
                                 accept_multiple_files=True, key="upload_input")
        code = st.text_input("Album code", key="upload_code", placeholder="SSC042").strip().upper()
        has_input = bool(files)
        entries, uploads = upload_entries(files)

    if has_input and not problem:
        n = len(entries)
        prefix = re.match(r"(EPP|RC|SSC)", code or "", flags=re.IGNORECASE)
        detected = rules.catalog_code(prefix.group(1)) if prefix else None
        if not n:
            problem = ("No audio files were found behind that link." if source == "Dropbox link"
                       else "None of those files are audio.")
        elif not code:
            problem = ("The album code couldn't be read from the name. Type it in." if source == "Dropbox link"
                       else "Type the album code for these files.")
        elif ss.catalog_choice and detected and detected != ss.catalog_choice:
            problem = (f"This is {code}, which is {CATALOG_NAMES[detected]} — "
                       f"not {CATALOG_NAMES[ss.catalog_choice]}.")
        else:
            minutes = max(1, round(n * SECONDS_PER_TRACK / 60))
            st.success(f"{code} · {n} audio file{'' if n == 1 else 's'} found · "
                       f"about {minutes} minute{'' if minutes == 1 else 's'}")
            if auto:
                st.caption(f"Plus {len(auto)} alt mixes and cutdowns, described from their folder names.")
            if check.get("kind") == "file":
                st.caption("A single file runs through the same listen and checks as a track in an album.")
            if any(r["code"] == code for r in (recent_albums(dropbox_configured) if dropbox_configured else [])):
                st.caption(f"{code} has been analyzed before. Analyzing again replaces its saved progress.")
    if problem:
        st.error(problem)
    if not gemini_api_key:
        st.caption("The Gemini API key is missing from the app's secrets.")

    ready = bool(ss.catalog_choice and entries and code and not problem and gemini_api_key)
    label = "Analyze" if len(entries) == 1 else "Analyze album"
    if st.button(label, type="primary", disabled=not ready, key="analyze_album"):
        start_album(ss.catalog_choice, code, entries, auto, check, uploads)
        st.rerun()

    st.divider()
    render_recent()


# ══════════════════════════════════════════════════════════════════════════════
# REVIEW
# ══════════════════════════════════════════════════════════════════════════════
def apply_table_edits(editor_key: str, ids: list):
    """
    Edits land on the track under its stable id. The editor is only remounted
    when a row is opened — remounting on every keystroke used to throw away
    what the user had just typed.
    """
    edits = (ss.get(editor_key) or {}).get("edited_rows", {})
    album = ss.album
    changed = opened = False
    for idx, change in edits.items():
        track = find_track(ids[int(idx)])
        if track is None:
            continue
        if change.get("Open"):
            ss.selected = track_key(track)
            ss.fix_mode = ""
            opened = True
        if track.get("PFD_Status") == gate.BLOCKED:
            continue  # blocked rows show a reason, not copy; they are fixed in the panel
        if "Description" in change and change["Description"] != track.get("Track Description", ""):
            track["Track Description"] = change["Description"]
            changed = True
        if ("Keywords" in change and not is_alt_or_cutdown(track)
                and change["Keywords"] != track.get("Keywords", "")):
            track["Keywords"] = change["Keywords"]
            changed = True
        if changed:
            ss.results[track_key(track)] = track
    if changed:
        eng.refresh_statuses(album, album["catalog"])
        save_album()
    if opened:
        ss.editor_nonce += 1


def render_reason(f: dict, tone: str = "pfd-reason"):
    """A blocked reason, in full: which check, the values, what it means, what to do."""
    x = gate.explain(f)
    lines = [f"<b>{html.escape(x['code'])} · {html.escape(x['check'])}</b>"]
    if x["values"]:
        lines.append(f"<code>{html.escape(x['values'])}</code>")
    if x["meaning"]:
        lines.append(html.escape(x["meaning"]))
    if x["action"]:
        lines.append(f"<b>What to do:</b> {html.escape(x['action'])}")
    st.markdown(f"<div class='{tone}'>" + "<br>".join(lines) + "</div>", unsafe_allow_html=True)


def status_label(track: dict) -> str:
    label = f"{DOT.get(track.get('PFD_Status'), '⚪')} {LABEL.get(track.get('PFD_Status'), '')}"
    return label + (" · Manual" if track.get("PFD_Manual") else "")


def render_album_details(album: dict):
    catalog = album["catalog"]
    descs = [t.get("Track Description", "") for t in album["tracks"]
             if t.get("Track Description") and not is_alt_or_cutdown(t) and t.get("PFD_Status") != gate.BLOCKED]
    ver = ss.field_ver
    with st.expander("Album details", expanded=False):
        if not claude_api_key:
            st.caption("The Claude API key is missing, so album details can't be written here.")

        if catalog == "EPP":
            st.markdown("**Lane**")
            names = rules.lane_names()
            labels = {l["name"]: f"{l['name']} ({l['status']})" for l in rules.lanes()}
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            current = album.get("lane") or album.get("lane_proposed") or names[0]
            chosen = c1.selectbox("Lane", names, index=names.index(current), format_func=lambda n: labels[n],
                                  key=f"lane_{ver}")
            if c2.button("Suggest", key="lane_suggest", disabled=not claude_api_key):
                try:
                    album["lane_proposed"] = eng.propose_lane(album["tracks"], claude_api_key)
                    ss.field_ver += 1
                    save_album()
                except (ClaudeError, ValueError) as exc:
                    report("Lane suggestion failed — pick one by hand", exc)
                st.rerun()
            if album.get("lane"):
                st.caption(f"Confirmed: {album['lane']} — the first keyword and first Fits tag on every track.")
            if chosen != album.get("lane") and st.button("Confirm lane", key="lane_confirm"):
                eng.apply_lane(album, chosen)
                eng.refresh_statuses(album, catalog)
                save_album()
                st.rerun()
            st.divider()

        st.markdown("**Album description**")
        text = st.text_area("Album description", value=album.get("album_description", ""), height=80,
                            label_visibility="collapsed", key=f"album_desc_{ver}")
        if text != album.get("album_description", ""):
            album["album_description"] = text
            save_album()
        for r in gate.album_description_reasons(text, catalog) if text else []:
            st.caption(f"⚠️ {gate.sentence(r)}")
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        direction = c1.text_input("Direction (optional)", key="album_desc_direction",
                                  placeholder="e.g. lead with the breath sounds")
        if c2.button("Write it" if not text else "Write again", key="album_desc_write",
                     disabled=not (claude_api_key and descs)):
            try:
                with st.spinner("Writing…"):
                    album["album_description"] = eng.generate_album_description(
                        descs, catalog, claude_api_key, previous=text, guidance=direction)
                ss.field_ver += 1
                save_album()
            except ClaudeError as exc:
                report("Album description failed", exc)
            st.rerun()

        st.divider()
        st.markdown("**Album name**")
        options = album.get("album_name_candidates") or []
        if options:
            current = album.get("album_name_selected") or options[0]
            pick = st.radio("Pick the name", options, index=options.index(current) if current in options else 0,
                            key=f"album_name_{ver}", label_visibility="collapsed",
                            captions=[(album.get("album_name_rationales") or {}).get(o, "") for o in options])
            if pick != album.get("album_name_selected"):
                album["album_name_selected"] = pick
                save_album()
        if st.button("Suggest five names", key="album_names_write",
                     disabled=not (claude_api_key and album.get("album_description"))):
            try:
                with st.spinner("Thinking of names…"):
                    out = eng.generate_album_names(album["album_description"], catalog, claude_api_key, descs)
                album["album_name_candidates"] = [n["name"] for n in out["names"]]
                album["album_name_rationales"] = {n["name"]: n["rationale"] for n in out["names"]}
                album["album_name_selected"] = album["album_name_candidates"][0] if out["names"] else ""
                ss.field_ver += 1
                save_album()
            except ClaudeError as exc:
                report("Album names failed", exc)
            st.rerun()

        st.divider()
        st.markdown("**MailChimp intro**")
        intro = st.text_area("MailChimp intro", value=album.get("mailchimp_intro", ""), height=120,
                             label_visibility="collapsed", key=f"mailchimp_{ver}")
        if intro != album.get("mailchimp_intro", ""):
            album["mailchimp_intro"] = intro
            save_album()
        if intro:
            words = len(intro.split())
            if not 40 <= words <= 70:
                st.caption(f"⚠️ {words} words (the spec is 40–70).")
            if "!" in intro or re.search(r"\bexcited\b", intro, re.IGNORECASE):
                st.caption("⚠️ No exclamation marks and no \"excited\".")
        if st.button("Write intro", key="mailchimp_write",
                     disabled=not (claude_api_key and album.get("album_name_selected"))):
            try:
                with st.spinner("Writing…"):
                    album["mailchimp_intro"] = eng.generate_mailchimp_intro(
                        album["album_name_selected"], album.get("album_description", ""), catalog, claude_api_key, descs)
                ss.field_ver += 1
                save_album()
            except ClaudeError as exc:
                report("MailChimp intro failed", exc)
            st.rerun()

        st.divider()
        st.markdown("**Cover prompts**")
        blocks = [b.strip() for b in (album.get("cover_art") or "").split("\n\n") if b.strip()]
        for i, block in enumerate(blocks):
            st.code(block, language=None, wrap_lines=True)
        if st.button("Write cover prompts", key="cover_write",
                     disabled=not (claude_api_key and album.get("album_name_selected"))):
            try:
                with st.spinner("Writing…"):
                    keywords = ", ".join(t.get("Keywords", "") for t in album["tracks"] if t.get("Keywords"))
                    album["cover_art"] = eng.generate_cover_art_prompts(
                        album["album_name_selected"], album.get("album_description", ""), catalog, [],
                        claude_api_key, track_descriptions=descs, keywords=keywords)
                save_album()
            except ClaudeError as exc:
                report("Cover prompts failed", exc)
            st.rerun()


def rerun_listen(track: dict, correction: str = ""):
    album = ss.album
    with st.spinner("Listening again…"):
        try:
            data = track_bytes(track)
            new = eng.process_track(track["Title"], track.get("Mix Type", "full"), data, track_extension(track),
                                    album["catalog"], gemini_api_key, claude_api_key, album_lane(),
                                    track.get("Source Path", ""), track.get("Parent Track", ""),
                                    correction=correction, track_id=track_key(track))
            new["Upload Key"] = track.get("Upload Key", "")
            put_track(new)   # the old result stands until this one is ready
        except Exception as exc:
            report(f"Couldn't listen again to {track['Title']}", exc)
            return
    eng.refresh_statuses(album, album["catalog"])
    save_album()
    ss.fix_mode = ""
    st.rerun()


def render_compare(track: dict):
    album = ss.album
    entry = album.setdefault("writer_test", {}).get(track_key(track))
    if st.button("Write three versions", key=f"compare_{track_key(track)}", disabled=not track.get("analysis")):
        with st.spinner("Writing three versions…"):
            variants = eng.writer_variants(track, album["catalog"], claude_api_key, album_lane())
        order = list(WRITER_MODES)
        random.shuffle(order)
        album["writer_test"][track_key(track)] = {"variants": variants, "order": order, "pick": None}
        save_album()
        st.rerun()
    if entry:
        labels = [f"Version {i}" for i in range(1, len(entry["order"]) + 1)]
        for label, mode in zip(labels, entry["order"]):
            st.markdown(f"**{label}.** {entry['variants'].get(mode) or '_(this version failed)_'}")
        choice = st.radio("The one you'd ship", labels, horizontal=True, key=f"compare_pick_{track_key(track)}",
                          index=None if entry["pick"] is None else entry["order"].index(entry["pick"]))
        if choice:
            mode = entry["order"][labels.index(choice)]
            if entry["pick"] != mode and entry["variants"].get(mode):
                entry["pick"] = mode
                track["Track Description"] = entry["variants"][mode]
                eng.refresh_statuses(album, album["catalog"])
                save_album()
                st.rerun()


def render_fix_panel(track: dict):
    album = ss.album
    catalog = album["catalog"]
    status = track.get("PFD_Status")
    st.divider()
    head, close = st.columns([6, 1], vertical_alignment="center")
    head.markdown(f"### {DOT.get(status, '⚪')} {track['Title']}")
    if close.button("Close", key="fix_close"):
        ss.selected = None
        ss.fix_mode = ""
        st.rerun()

    if not is_alt_or_cutdown(track) and (track.get("Upload Key") or (track.get("Source Path") and dropbox_configured)):
        try:
            audio = track_audio(track)
            if audio:
                st.audio(audio, format=AUDIO_FORMATS.get(track_extension(track), "audio/mpeg"))
            else:
                st.caption("That file was uploaded in an earlier session, so it can't be played here.")
        except Exception as exc:
            report("Couldn't load the audio", exc)

    if status == gate.BLOCKED:
        for reason in gate.normalize(track.get("PFD_Block_Reasons")):
            render_reason(reason)
        if is_alt_or_cutdown(track):
            st.caption("This version follows its full mix. Fix the full mix, or skip this one.")
        elif track.get("PFD_Reason_Kind") == "text" and track.get("Track Description"):
            st.caption("What it says now:")
            st.write(track["Track Description"])

        c = st.columns(5)
        can_listen = can_listen_again(track)
        if c[0].button("Run again", key="fix_run", type="primary", disabled=not can_listen):
            if track.get("PFD_Reason_Kind") == "text" and track.get("analysis"):
                with st.spinner("Writing again…"):
                    eng.try_write(track, catalog, gemini_api_key, claude_api_key, album_lane(), is_redo=True)
                eng.refresh_statuses(album, catalog)
                save_album()
                st.rerun()
            rerun_listen(track)
        if c[1].button("Tell it what's true", key="fix_correct", disabled=not can_listen):
            ss.fix_mode = "correct"
        if c[2].button("I'll write it", key="fix_manual", disabled=is_alt_or_cutdown(track)):
            ss.fix_mode = "manual"
        if c[3].button("Override", key="fix_override",
                       help="You listened and you accept this track. It passes with your reason, "
                            "the time, and the block it overrode, all recorded in the export."):
            ss.fix_mode = "override"
        if c[4].button("Skip this track", key="fix_skip", type="tertiary"):
            eng.skip(track)
            eng.refresh_statuses(album, catalog)
            save_album()
            ss.selected = None
            st.rerun()

        if ss.fix_mode == "override":
            why = st.text_input("Reason for override (required)", key=f"override_{track_key(track)}",
                                placeholder="e.g. free time, no steady tempo — librosa has it wrong")
            st.caption("The track passes. Your reason, the time, and the block you overrode are kept on the "
                       "row and written into the export. The original reason is never deleted.")
            if st.button("Override and continue", key="fix_override_go", type="primary",
                         disabled=not why.strip()):
                try:
                    with st.spinner("Recording the override and writing the description…"):
                        eng.override_track(track, catalog, gemini_api_key, claude_api_key, why, album_lane())
                    put_track(track)
                except Exception as exc:
                    report(f"Couldn't override {track['Title']}", exc)
                else:
                    eng.refresh_statuses(album, catalog)
                    save_album()
                    ss.fix_mode = ""
                    st.rerun()
        elif ss.fix_mode == "correct":
            correction = st.text_input("What's true about this track?", key=f"correction_{track_key(track)}",
                                       placeholder="e.g. There are no drums — the hits are timpani. It fades out.")
            if st.button("Listen again with this", key="fix_correct_go", disabled=not correction.strip()):
                rerun_listen(track, correction=correction)
        elif ss.fix_mode == "manual":
            text = st.text_area("Description", key=f"manual_{track_key(track)}", height=110,
                                placeholder="Two or three sentences, then the Fits line. Fits: …")
            keywords = ""
            if not track.get("analysis"):
                keywords = st.text_input("Keywords (12–18, comma-separated)", key=f"manual_kw_{track_key(track)}")
            if st.button("Save", key="fix_manual_save", type="primary", disabled=not text.strip()):
                try:
                    with st.spinner("Saving and writing keywords…"):
                        problems = eng.manual_description(track, text, catalog, gemini_api_key, album_lane(), keywords)
                except Exception as exc:
                    report("Keywords couldn't be written for the manual description", exc)
                    problems = []
                if problems:
                    for p in problems:
                        render_reason(p)
                else:
                    eng.refresh_statuses(album, catalog)
                    save_album()
                    ss.fix_mode = ""
                    st.rerun()
        return

    if status == SKIPPED:
        st.caption("Skipped — this track is left out of the export.")
        if st.button("Include it again", key="fix_unskip"):
            eng.skip(track, False)
            eng.refresh_statuses(album, catalog)
            save_album()
            st.rerun()
        return

    unsure = remaining_uncertain(track)
    if unsure:
        st.markdown('<div class="pfd-note">It wasn\'t sure about these, so the description doesn\'t mention them. '
                    'If you can hear one, add it and the description is rewritten (no new listen).</div>',
                    unsafe_allow_html=True)
        for path in unsure:
            c = st.columns([3, 1, 1], vertical_alignment="center")
            reason = (find_observation(track.get("analysis"), path) or {}).get("note") or ""
            c[0].markdown(f"**{family_label(path).capitalize()}**" + (f" — {reason}" if reason else ""))
            if c[1].button("Add it", key=f"add_{path}", disabled=not gemini_api_key):
                with st.spinner("Rewriting…"):
                    eng.add_family(track, path, catalog, gemini_api_key, claude_api_key, album_lane())
                eng.refresh_statuses(album, catalog)
                save_album()
                st.rerun()
            if c[2].button("Leave it out", key=f"dismiss_{path}"):
                eng.dismiss_family(track, path, catalog, album_lane())
                eng.refresh_statuses(album, catalog)
                save_album()
                st.rerun()

    override = track.get("PFD_Override")
    if override:
        at = override.get("at", "")[:16].replace("T", " ") if isinstance(override, dict) else ""
        st.markdown(f'<div class="pfd-note"><b>Override</b> — {html.escape(override_reason(track))}'
                    + (f"<br>Recorded {at} UTC" if at else "")
                    + (("<br>It overrode: " + html.escape(" · ".join(override.get("overrode") or [])))
                       if isinstance(override, dict) and override.get("overrode") else "")
                    + "</div>", unsafe_allow_html=True)
    note = (track.get("PFD_Gate") or {}).get("override_note")
    if note:
        st.caption(note)
    if track.get("Track Description"):
        st.write(track["Track Description"])
    if track.get("Sections"):
        st.caption(f"Sections: {track['Sections']}")
    if ss.get("compare_styles") and track.get("analysis"):
        st.markdown("**Compare writing styles**")
        render_compare(track)
    if not is_alt_or_cutdown(track) and st.button("Skip this track", key="ready_skip", type="tertiary"):
        eng.skip(track)
        eng.refresh_statuses(album, catalog)
        save_album()
        ss.selected = None
        st.rerun()


def render_review():
    album = ss.album
    catalog = album["catalog"]
    restore_results(album)
    eng.refresh_statuses(album, catalog)
    tracks = album["tracks"]
    counts = eng.status_counts(tracks)
    needs = counts["blocked"] + counts["uncertain"]

    st.markdown(f"#### {album['album_code']} · {CATALOG_NAMES.get(catalog, catalog)} · {album.get('album_folder_name', '')}")
    if album.get("pending"):
        st.caption(f"{len(album['pending'])} tracks haven't been listened to yet — resume from Start.")
    render_album_details(album)

    if "review_filter" not in ss:
        ss.review_filter = "needs" if needs else "all"
    ready_n = counts["ready"] + counts["override"]
    options = {"all": f"All ({len(tracks)})", "needs": f"Needs a look ({needs})", "ready": f"Ready ({ready_n})"}
    choice = st.segmented_control("Show", list(options), format_func=lambda k: options[k], key="review_filter",
                                  label_visibility="collapsed")
    choice = choice or "all"
    shown = [t for t in tracks if choice == "all"
             or (choice == "needs" and t.get("PFD_Status") in (gate.BLOCKED, gate.PASSED_WITH_UNCERTAINTY))
             or (choice == "ready" and t.get("PFD_Status") in (gate.PASSED, OVERRIDE))]

    if not shown:
        st.caption("Nothing here.")
    else:
        ids = [track_key(t) for t in shown]
        df = pd.DataFrame([{
            "Open": False,
            "Status": status_label(t),
            "Track": t["Title"],
            "Description": t.get("Track Description", ""),   # never replaced by a reason
            "Why blocked": (" · ".join(gate.summary(f) for f in gate.normalize(t.get("PFD_Block_Reasons")))
                            if t.get("PFD_Status") == gate.BLOCKED
                            else (f"Override: {override_reason(t)}" if t.get("PFD_Status") == OVERRIDE else "")),
            "Keywords": t.get("Keywords", ""),
            "Ending": t.get("Ending Type", ""),
        } for t in shown])
        editor_key = f"review_editor_{ss.editor_nonce}"
        st.data_editor(
            df, key=editor_key, hide_index=True, use_container_width=True, num_rows="fixed",
            disabled=["Status", "Track", "Why blocked", "Ending"],
            column_config={
                "Open": st.column_config.CheckboxColumn("Open", width="small", help="Open this track below"),
                "Status": st.column_config.TextColumn("Status", width="small"),
                "Track": st.column_config.TextColumn("Track", width="medium"),
                "Description": st.column_config.TextColumn("Description", width="large"),
                "Why blocked": st.column_config.TextColumn("Why blocked", width="medium",
                                                           help="Open the track for the full reason"),
                "Keywords": st.column_config.TextColumn("Keywords", width="medium"),
                "Ending": st.column_config.TextColumn("Ending", width="small"),
            },
            on_change=apply_table_edits, args=(editor_key, ids),
        )
        st.caption("Tick Open to see a track below. Your text stays in the Description column; "
                   "the reason a track is blocked sits beside it.")

    selected = find_track(ss.selected) if ss.selected else None
    if selected:
        render_fix_panel(selected)


# ══════════════════════════════════════════════════════════════════════════════
# EXPORT
# ══════════════════════════════════════════════════════════════════════════════
def render_export():
    album = ss.album
    catalog = album["catalog"]
    _, issues = eng.validate_data(album, catalog)
    counts = eng.status_counts(album["tracks"])
    lane_missing = catalog == "EPP" and not album.get("lane")

    st.markdown(f"#### {album['album_code']} · {CATALOG_NAMES.get(catalog, catalog)}")
    c = st.columns(5)
    c[0].metric("Ready", counts["ready"])
    c[1].metric("Ready with note", counts["uncertain"])
    c[2].metric("Override", counts["override"])
    c[3].metric("Blocked", counts["blocked"])
    c[4].metric("Skipped", counts["skipped"])

    if counts["blocked"]:
        st.warning(f"{counts['blocked']} track(s) are still blocked. Fix or skip them in Review.")
    if lane_missing:
        st.warning("Confirm the EPP lane in Review → Album details first.")
    album_issues = [i for i in issues if i.startswith(("Album description", "Album name"))]
    if album_issues:
        with st.expander(f"Album details to check ({len(album_issues)})"):
            for i in album_issues:
                st.caption(gate.sentence(i))

    if st.button("Export for SourceAudio", type="primary", key="export_go",
                 disabled=bool(counts["blocked"] or lane_missing or album.get("pending"))):
        exported = len([t for t in album["tracks"] if not t.get("PFD_Skipped")])
        summary = (f"{exported} tracks exported · {counts['ready']} ready · {counts['uncertain']} with a note"
                   + (f" · {counts['skipped']} skipped" if counts["skipped"] else ""))
        try:
            dbx = dbx_client()
            reference = capture.read_columns_reference(dbx)
            zip_bytes, zip_name, draft_path = capture.export_album(dbx, album, catalog, album["album_code"], reference)
            picks = {k: v for k, v in (album.get("writer_test") or {}).items() if v.get("pick")}
            if picks:
                lines = [f"# Compare writing styles — {album['album_code']} — {datetime.date.today().isoformat()}", "",
                         "## Tally", ""] + [f"- {m}: {sum(1 for v in picks.values() if v['pick'] == m)}"
                                            for m in WRITER_MODES] + [""]
                for title, v in picks.items():
                    lines += [f"### {title}", f"Picked: {v['pick']}"] + \
                             [f"- [{m}] {v['variants'].get(m, '')}" for m in v["order"]] + [""]
                capture.write_writer_test(dbx, "\n".join(lines))
            album["exported_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            album["run_status"] = "exported"
            save_album(mark_dirty=False)
            ss.dirty = False
            ss.export_result = {"zip": zip_bytes, "name": zip_name, "draft": draft_path, "summary": summary}
            send_ntfy("📦 PFD — album exported", f"{album['album_code']}: {summary}. DRAFT saved to {draft_path}.")
        except Exception as exc:
            report("The DRAFT was not saved to Dropbox — this export is not captured", exc)
            zip_bytes, zip_name = capture.build_zip(album, catalog, album["album_code"])
            ss.export_result = {"zip": zip_bytes, "name": zip_name, "draft": "", "summary": summary}

    result = ss.export_result
    if result:
        st.success(result["summary"])
        st.download_button("Download ZIP", result["zip"], file_name=result["name"], mime="application/zip",
                           type="primary", key="export_download")
        if result["draft"]:
            st.caption(f"Saved to Dropbox: {result['draft']}")


# ══════════════════════════════════════════════════════════════════════════════
if ss.step == "review" and ss.album:
    render_review()
elif ss.step == "export" and ss.album:
    render_export()
else:
    render_start()
