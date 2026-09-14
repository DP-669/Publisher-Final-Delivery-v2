"""
PFD feedback log.
Logs AI drafts, user guidance, and accepted finals to Dropbox. v3's main
learning signal is DRAFT vs FINAL (capture.py); this log stays as the
fine-grained record of in-app redos. Failures are visible, never swallowed.
"""
import json
import logging
from datetime import datetime, timezone

from pfd_errors import report

log = logging.getLogger("pfd")

EDIT_LOG_PATH = "/PFD-App/pfd-edit-log.json"
LOG_THRESHOLD = 3  # revision pass available after this many unique albums


def _get_dbx(dropbox_token=None):
    """Return a Dropbox client. Prefers refresh-token auth from secrets."""
    from engine import IngestionEngine
    return IngestionEngine.get_dropbox_client(None, dropbox_token)


def _is_not_found(exc) -> bool:
    err = getattr(exc, "error", None)
    try:
        return bool(err and err.is_path() and err.get_path().is_not_found())
    except AttributeError:
        return False


def load_edit_log(dropbox_token=None) -> list:
    """The edit log from Dropbox; an empty list only when the file does not exist yet."""
    import dropbox as dbx_mod
    dbx = _get_dbx(dropbox_token)
    try:
        _, res = dbx.files_download(EDIT_LOG_PATH)
    except dbx_mod.exceptions.ApiError as exc:
        if _is_not_found(exc):
            return []
        raise
    return json.loads(res.content)


def save_edit_log(entries: list, dropbox_token=None):
    import dropbox as dbx_mod
    dbx = _get_dbx(dropbox_token)
    data = json.dumps(entries, indent=2, ensure_ascii=False).encode("utf-8")
    dbx.files_upload(data, EDIT_LOG_PATH, mode=dbx_mod.files.WriteMode.overwrite)


def log_interaction(catalog, album_name, tab, track_title, iterations, final, dropbox_token=None) -> bool:
    """Append one interaction. A failure is shown to the user and returns False."""
    try:
        entries = load_edit_log(dropbox_token)
        entries.append({
            "id": len(entries) + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "catalog": catalog, "album": album_name, "tab": tab,
            "track": track_title, "iterations": iterations, "final": final,
        })
        save_edit_log(entries, dropbox_token)
        return True
    except Exception as exc:
        report("Feedback log write to Dropbox failed", exc)
        return False


def count_logged_albums(dropbox_token=None) -> int:
    try:
        return len(set(e["album"] for e in load_edit_log(dropbox_token)))
    except Exception as exc:
        report("Could not read the feedback log", exc)
        return 0


def is_revision_ready(dropbox_token=None) -> bool:
    return count_logged_albums(dropbox_token) >= LOG_THRESHOLD


def build_revision_prompt(entries: list, catalog: str) -> str:
    catalog_entries = [e for e in entries if e.get("catalog") == catalog] or entries
    sample = catalog_entries[-50:]
    return f"""You are analyzing a history of AI-generated music publishing outputs and the edits/feedback that shaped them.

EDIT LOG (last {len(sample)} interactions, catalog: {catalog}):
{json.dumps(sample, indent=2)}

TASK:
1. Identify patterns in what was REJECTED.
2. Identify patterns in what was ACCEPTED.
3. Identify vocabulary corrections.
4. Propose SPECIFIC edits to the TUNABLE section of PFD_RULES.md, one at a time, based purely on the evidence.

Output sections: REJECTION PATTERNS / ACCEPTANCE PATTERNS / VOCABULARY CORRECTIONS / PROPOSED PFD_RULES.md EDITS
Be specific. Reference actual examples from the log."""
