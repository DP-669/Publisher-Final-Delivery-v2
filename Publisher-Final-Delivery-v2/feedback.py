"""
PFD Self-Improving Feedback Loop
Logs AI drafts, user guidance, and accepted finals to Dropbox.
After LOG_THRESHOLD albums, a revision pass can be triggered.
"""
import json
from datetime import datetime, timezone

EDIT_LOG_PATH = "/PFD-App/pfd-edit-log.json"
LOG_THRESHOLD = 3  # revision pass available after this many unique albums


def _get_dbx(dropbox_token=None):
    """Return a Dropbox client. Prefers refresh-token auth from st.secrets."""
    import dropbox as dbx_mod
    try:
        import streamlit as st
        app_key = st.secrets.get("DROPBOX_APP_KEY")
        app_secret = st.secrets.get("DROPBOX_APP_SECRET")
        refresh_token = st.secrets.get("DROPBOX_REFRESH_TOKEN")
        if app_key and app_secret and refresh_token:
            return dbx_mod.Dropbox(
                oauth2_refresh_token=refresh_token,
                app_key=app_key,
                app_secret=app_secret,
            )
    except Exception:
        pass
    return dbx_mod.Dropbox(dropbox_token)


def load_edit_log(dropbox_token=None) -> list:
    """Load the edit log from Dropbox. Returns empty list if not found."""
    try:
        import dropbox as dbx_mod
        dbx = _get_dbx(dropbox_token)
        _, res = dbx.files_download(EDIT_LOG_PATH)
        return json.loads(res.content)
    except Exception:
        return []


def save_edit_log(log: list, dropbox_token=None):
    """Write the full log back to Dropbox."""
    import dropbox as dbx_mod
    dbx = _get_dbx(dropbox_token)
    data = json.dumps(log, indent=2, ensure_ascii=False).encode("utf-8")
    dbx.files_upload(data, EDIT_LOG_PATH, mode=dbx_mod.files.WriteMode.overwrite)


def log_interaction(catalog, album_name, tab, track_title, iterations, final, dropbox_token=None):
    """Append one interaction to the edit log. Never raises."""
    try:
        log = load_edit_log(dropbox_token)
        entry = {
            "id": len(log) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "catalog": catalog, "album": album_name, "tab": tab,
            "track": track_title, "iterations": iterations, "final": final,
        }
        log.append(entry)
        save_edit_log(log, dropbox_token)
    except Exception:
        pass


def count_logged_albums(dropbox_token=None) -> int:
    try:
        log = load_edit_log(dropbox_token)
        return len(set(e["album"] for e in log))
    except Exception:
        return 0


def is_revision_ready(dropbox_token=None) -> bool:
    return count_logged_albums(dropbox_token) >= LOG_THRESHOLD


def build_revision_prompt(log: list, catalog: str) -> str:
    catalog_entries = [e for e in log if e.get("catalog") == catalog] or log
    sample = catalog_entries[-50:]
    entries_text = json.dumps(sample, indent=2)
    return f"""You are analyzing a history of AI-generated music publishing outputs and the edits/feedback that shaped them.

EDIT LOG (last {len(sample)} interactions, catalog: {catalog}):
{entries_text}

TASK:
1. Identify patterns in what was REJECTED.
2. Identify patterns in what was ACCEPTED.
3. Identify vocabulary corrections.
4. For each tab type present, propose SPECIFIC prompt changes based purely on the evidence.

Output sections: REJECTION PATTERNS / ACCEPTANCE PATTERNS / VOCABULARY CORRECTIONS / PROPOSED PROMPT CHANGES
Be specific. Reference actual examples from the log."""
