"""
PFD Session Persistence — auto-save and recovery via Dropbox.

Saves to: /rMG PFD Progress/{catalog}_{album}_progress.json
           /rMG PFD Progress/{catalog}_{album}_progress.csv

Rules:
- save_progress() never raises — failures are silent (logged only)
- Files are overwritten on each save (one current file per session)
- list_sessions() downloads JSON files to read metadata; fine for <=20 sessions
"""
import json
import re
import datetime
import pandas as pd

PROGRESS_FOLDER = "/rMG PFD Progress"


# ── Path helpers ───────────────────────────────────────────────────────────────

def _slug(text: str, max_len: int = 40) -> str:
    """Make a filesystem-safe slug from any string."""
    s = re.sub(r"[^a-z0-9]+", "_", (text or "session").lower()).strip("_")
    return s[:max_len] or "session"


def _json_path(catalog: str, album: str) -> str:
    return f"{PROGRESS_FOLDER}/{_slug(catalog)}_{_slug(album)}_progress.json"


def _csv_path(catalog: str, album: str) -> str:
    return f"{PROGRESS_FOLDER}/{_slug(catalog)}_{_slug(album)}_progress.csv"


def _album_name(app_data: dict, pipe_state: dict) -> str:
    """Extract the album name from wherever it's available."""
    return (
        pipe_state.get("album_name")
        or app_data.get("album_name_folder")
        or "session"
    )


# ── Dropbox helpers ────────────────────────────────────────────────────────────

def _dbx(token: str):
    """Return (client, module) for the Dropbox SDK."""
    import dropbox as dbx_mod
    return dbx_mod.Dropbox(token), dbx_mod


def _ensure_folder(client, dbx_mod):
    try:
        client.files_create_folder_v2(PROGRESS_FOLDER)
    except dbx_mod.exceptions.ApiError:
        pass  # Already exists — ignore


# ── Stage detection ────────────────────────────────────────────────────────────

def _detect_stages(app_data: dict) -> dict:
    tracks = app_data.get("tracks", [])
    return {
        "ingest":             bool(tracks),
        "track_descriptions": any(t.get("Track Description") for t in tracks),
        "album_description":  bool(app_data.get("album_description")),
        "album_name":         bool(app_data.get("album_name") or app_data.get("album_name_selected")),
        "cover_art":          bool(app_data.get("cover_art")),
        "mailchimp_intro":    bool(app_data.get("mailchimp_intro")),
    }


def _furthest_tab(stages: dict) -> int:
    """Return the index of the most advanced completed stage (for navigation on restore)."""
    if stages.get("mailchimp_intro"):  return 6
    if stages.get("cover_art"):        return 5
    if stages.get("album_name"):       return 4
    if stages.get("album_description"):return 3
    if stages.get("track_descriptions"):return 2
    if stages.get("ingest"):           return 2   # jump to Tab 02 so user can start descriptions
    return 1


# ── Public API ─────────────────────────────────────────────────────────────────

def save_progress(token: str, app_data: dict, pipe_state: dict) -> bool:
    """
    Persist the full session to Dropbox as JSON + CSV.
    Returns True on success, False on any failure (never raises).
    """
    try:
        catalog  = app_data.get("catalog", "session")
        album    = _album_name(app_data, pipe_state)
        stages   = _detect_stages(app_data)

        payload = {
            "save_time":    datetime.datetime.now().isoformat(),
            "version":      "1",
            "catalog":      catalog,
            "album_name":   album,
            "stages":       stages,
            "furthest_tab": _furthest_tab(stages),
            "app_data":     app_data,
            # Lightweight pipeline metadata (not the full queue)
            "pipeline_meta": {
                "status":          pipe_state.get("status", ""),
                "album_path":      pipe_state.get("album_path", ""),
                "processed_count": pipe_state.get("processed_count", 0),
                "total_to_analyze":pipe_state.get("total_to_analyze", 0),
            },
        }

        client, dbx_mod = _dbx(token)
        _ensure_folder(client, dbx_mod)

        # ── JSON ──────────────────────────────────────────────────────────────
        json_bytes = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        client.files_upload(
            json_bytes,
            _json_path(catalog, album),
            mode=dbx_mod.files.WriteMode.overwrite,
            mute=True,
        )

        # ── CSV (track data readable in Excel) ────────────────────────────────
        tracks = app_data.get("tracks", [])
        if tracks:
            rows = []
            for t in tracks:
                cdl_val = t.get("Trailer Description") or t.get("Campaign Description") or ""
                rows.append({
                    "Title":                        t.get("Title", ""),
                    "Mix Type":                     t.get("Mix Type", ""),
                    "Track Description":            t.get("Track Description", ""),
                    "Overall Consensus":            t.get("Overall Consensus", ""),
                    "Trailer/Campaign Description": cdl_val,
                    "Editor Description":           t.get("Editor Description", ""),
                    "Supervisor Description":       t.get("Supervisor Description", ""),
                    "Keywords":                     t.get("Keywords", ""),
                    "Tip":                          t.get("Tip", ""),
                })
            csv_bytes = pd.DataFrame(rows).to_csv(index=False).encode("utf-8")
            client.files_upload(
                csv_bytes,
                _csv_path(catalog, album),
                mode=dbx_mod.files.WriteMode.overwrite,
                mute=True,
            )

        return True

    except Exception as exc:
        print(f"[PFD persistence] Silent save failure: {exc}")
        return False


def list_sessions(token: str, max_sessions: int = 8) -> list:
    """
    Return a list of saved session dicts, newest first.
    Each dict has: display, save_time, stages, furthest_tab, catalog,
                   album_name, app_data.
    """
    try:
        client, _ = _dbx(token)
        try:
            result = client.files_list_folder(PROGRESS_FOLDER, recursive=False)
        except Exception:
            return []

        sessions = []
        for entry in result.entries:
            if not (hasattr(entry, "client_modified") and entry.name.endswith("_progress.json")):
                continue
            try:
                _, resp = client.files_download(entry.path_lower)
                data = json.loads(resp.content.decode("utf-8"))
                stages = data.get("stages", {})
                stage_labels = {
                    "ingest": "Ingest",
                    "track_descriptions": "Descriptions",
                    "album_description": "Album Desc",
                    "album_name": "Album Name",
                    "cover_art": "Cover Art",
                    "mailchimp_intro": "MailChimp",
                }
                stage_summary = " · ".join(
                    label for key, label in stage_labels.items() if stages.get(key)
                ) or "Empty"
                sessions.append({
                    "display":      f"{data.get('catalog','')} · {data.get('album_name','')}",
                    "stage_summary": stage_summary,
                    "save_time":    data.get("save_time", ""),
                    "stages":       stages,
                    "furthest_tab": data.get("furthest_tab", 1),
                    "catalog":      data.get("catalog", ""),
                    "album_name":   data.get("album_name", ""),
                    "app_data":     data.get("app_data"),
                    "pipeline_meta":data.get("pipeline_meta", {}),
                })
            except Exception:
                continue

        sessions.sort(key=lambda x: x["save_time"], reverse=True)
        return sessions[:max_sessions]

    except Exception as exc:
        print(f"[PFD persistence] list_sessions failed: {exc}")
        return []


def delete_progress(token: str, catalog: str, album: str):
    """Remove progress files after a completed export. Silent on failure."""
    try:
        client, _ = _dbx(token)
        for path in [_json_path(catalog, album), _csv_path(catalog, album)]:
            try:
                client.files_delete_v2(path)
            except Exception:
                pass
    except Exception:
        pass
