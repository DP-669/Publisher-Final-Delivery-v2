"""
Capture: what the app produced (DRAFT) versus what Vesna ingested (FINAL).

    /PFD-App/albums/<ALBUMCODE>/<CATALOG>_<ALBUMCODE>_<album>_DRAFT.csv   written on export
    /PFD-App/albums/<ALBUMCODE>/<CATALOG>_<ALBUMCODE>_<album>_FINAL.csv   uploaded by Vesna
    /PFD-App/albums/<ALBUMCODE>/<CATALOG>_<ALBUMCODE>_<album>_DIFF.md     word-level edit distance

The difference between DRAFT and FINAL is how the system learns. Dropbox only;
nothing here ever writes to Google Drive.
"""
import io
import re
import zipfile
from datetime import date
from typing import Dict, List, Optional, Tuple

import pandas as pd

import gate
import rules

PFD_ROOT = "/PFD-App"
COLUMNS_REFERENCE_PATH = f"{PFD_ROOT}/reference/sourceaudio_columns.txt"
TESTS_FOLDER = f"{PFD_ROOT}/tests"

# The v2 column set, unchanged, plus album columns so DRAFT/FINAL can be
# compared on the album description, plus the two status columns at the end.
BASE_COLUMNS = ["Title", "Mix Type", "Track Description", "Overall Consensus",
                "{context}", "Editor Description", "Supervisor Description",
                "Keywords", "Tip", "Album", "Album Description"]
STATUS_COLUMNS = ["PFD_Status", "PFD_Block_Reasons"]

DIFF_FIELDS = {
    "track description": ["Track Description", "Description", "Track_Description", "Track Desc"],
    "keywords": ["Keywords", "Tags", "Keyword"],
    "album description": ["Album Description", "Album_Description", "Album Desc"],
}
TITLE_ALIASES = ["Title", "Track Title", "Track Name", "Track"]


# ── Names and paths ────────────────────────────────────────────────────────────

def _safe(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip()).strip("_")
    return s[:max_len] or "album"


def detect_album_code(*texts: str) -> str:
    """'…/EPP061 Body Works/…' -> 'EPP061'. Empty string when nothing matches."""
    for t in texts:
        m = re.search(r"(?<![A-Za-z])(EPP|RC|SSC)[\s_-]?(\d{2,4})(?!\d)", t or "", flags=re.IGNORECASE)
        if m:
            return f"{m.group(1).upper()}{m.group(2)}"
    return ""


def album_folder(album_code: str) -> str:
    return f"{PFD_ROOT}/albums/{_safe(album_code, 20)}"


def file_base(catalog: str, album_code: str, album: str) -> str:
    return f"{rules.catalog_code(catalog)}_{_safe(album_code, 20)}_{_safe(album)}"


def capture_paths(catalog: str, album_code: str, album: str) -> Dict[str, str]:
    folder = album_folder(album_code)
    base = file_base(catalog, album_code, album)
    return {k: f"{folder}/{base}_{k.upper()}.{ext}"
            for k, ext in (("draft", "csv"), ("final", "csv"), ("diff", "md"))}


# ── CSV ────────────────────────────────────────────────────────────────────────

def context_label(catalog: str) -> str:
    return "Campaign Description" if rules.catalog_code(catalog) == "EPP" else "Trailer Description"


def parse_columns_reference(text: str) -> List[str]:
    """One column per line, or a single comma-separated header line."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if len(lines) == 1 and "," in lines[0]:
        return [c.strip() for c in lines[0].split(",") if c.strip()]
    return lines


def _block_reasons(track: Dict) -> str:
    if (track.get("PFD_Status") or gate.BLOCKED) != gate.BLOCKED:
        return ""
    reasons = list(track.get("PFD_Block_Reasons") or []) or ["no status recorded"]
    if track.get("PFD_Human_Note"):
        reasons.append(f"human note: {track['PFD_Human_Note']}")
    return "; ".join(reasons)


def track_rows(app_data: Dict, catalog: str) -> pd.DataFrame:
    ctx = context_label(catalog)
    album = app_data.get("album_name_selected") or ""
    album_desc = app_data.get("album_description", "")
    rows = []
    for t in app_data.get("tracks", []):
        rows.append({
            "Title": t.get("Title", ""),
            "Mix Type": t.get("Mix Type", ""),
            "Track Description": t.get("Track Description", ""),
            "Overall Consensus": t.get("Overall Consensus", ""),
            ctx: t.get(ctx, ""),
            "Editor Description": t.get("Editor Description", ""),
            "Supervisor Description": t.get("Supervisor Description", ""),
            "Keywords": t.get("Keywords", ""),
            "Tip": t.get("Tip", ""),
            "Album": album,
            "Album Description": album_desc,
            "PFD_Status": t.get("PFD_Status") or gate.BLOCKED,
            "PFD_Block_Reasons": _block_reasons(t),
        })
    columns = [c.replace("{context}", ctx) for c in BASE_COLUMNS] + STATUS_COLUMNS
    return pd.DataFrame(rows, columns=columns)


def order_columns(df: pd.DataFrame, reference: Optional[List[str]]) -> pd.DataFrame:
    """Vesna's SourceAudio column order when given; our extra columns follow; status columns last."""
    if not reference:
        return df
    out = pd.DataFrame(index=df.index)
    for col in reference:
        out[col] = df[col] if col in df.columns else ""
    for col in df.columns:
        if col not in out.columns and col not in STATUS_COLUMNS:
            out[col] = df[col]
    for col in STATUS_COLUMNS:
        out[col] = df[col]
    return out


def build_csv(app_data: Dict, catalog: str, reference: Optional[List[str]] = None) -> bytes:
    return order_columns(track_rows(app_data, catalog), reference).to_csv(index=False).encode("utf-8")


def build_zip(app_data: Dict, catalog: str, album_code: str,
              reference: Optional[List[str]] = None) -> Tuple[bytes, str]:
    """One ZIP: one CSV plus the album text assets. Returns (bytes, zip file name)."""
    album = app_data.get("album_name_selected") or "album"
    base = file_base(catalog, album_code, album)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}.csv", build_csv(app_data, catalog, reference))
        zf.writestr("Album_Description.txt", app_data.get("album_description", ""))
        zf.writestr("Album_Names.txt", _names_text(app_data))
        zf.writestr("MailChimp_Intro.txt", app_data.get("mailchimp_intro", ""))
        zf.writestr("Cover_Art_Prompts.txt", app_data.get("cover_art", ""))
    return buf.getvalue(), f"{base}.zip"


def _names_text(app_data: Dict) -> str:
    selected = app_data.get("album_name_selected", "")
    names = app_data.get("album_name_candidates") or []
    lines = [f"Selected: {selected}", ""] + [f"- {n}" for n in names]
    return "\n".join(lines).strip() + "\n"


# ── Diff ───────────────────────────────────────────────────────────────────────

def word_edit_distance(a: str, b: str) -> int:
    """Levenshtein distance over words."""
    x, y = (a or "").split(), (b or "").split()
    prev = list(range(len(y) + 1))
    for i, wx in enumerate(x, 1):
        cur = [i]
        for j, wy in enumerate(y, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (wx != wy)))
        prev = cur
    return prev[-1]


def _col(df: pd.DataFrame, aliases: List[str]) -> Optional[str]:
    lower = {c.strip().lower(): c for c in df.columns}
    for a in aliases:
        if a.lower() in lower:
            return lower[a.lower()]
    return None


def _cell(v) -> str:
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def compute_diff(draft: pd.DataFrame, final: pd.DataFrame) -> Dict:
    """
    Per field: words changed / draft words. Rows are matched on title.
    Album description is compared once (first non-empty value on each side).
    """
    d_title, f_title = _col(draft, TITLE_ALIASES), _col(final, TITLE_ALIASES)
    if not d_title or not f_title:
        raise ValueError("Both CSVs need a Title column to be compared.")
    final_by_title = {_cell(r[f_title]).strip().lower(): r for _, r in final.iterrows()}

    result = {"fields": {}, "tracks": [], "unmatched": []}
    for field, aliases in DIFF_FIELDS.items():
        d_col, f_col = _col(draft, aliases), _col(final, aliases)
        stats = {"changed": 0, "words": 0, "pct": 0.0, "missing": not (d_col and f_col)}
        if stats["missing"]:
            result["fields"][field] = stats
            continue
        if field == "album description":
            dv = next((_cell(v) for v in draft[d_col] if _cell(v).strip()), "")
            fv = next((_cell(v) for v in final[f_col] if _cell(v).strip()), "")
            stats["changed"], stats["words"] = word_edit_distance(dv, fv), len(dv.split())
            if stats["changed"]:
                result["tracks"].append({"title": "(album)", "field": field, "draft": dv, "final": fv})
        else:
            for _, row in draft.iterrows():
                key = _cell(row[d_title]).strip().lower()
                frow = final_by_title.get(key)
                if frow is None:
                    if field == "track description":
                        result["unmatched"].append(_cell(row[d_title]))
                    continue
                dv, fv = _cell(row[d_col]), _cell(frow[f_col])
                dist = word_edit_distance(dv, fv)
                stats["changed"] += dist
                stats["words"] += len(dv.split())
                if dist:
                    result["tracks"].append({"title": _cell(row[d_title]), "field": field,
                                             "draft": dv, "final": fv})
        stats["pct"] = round(100.0 * stats["changed"] / stats["words"], 1) if stats["words"] else 0.0
        result["fields"][field] = stats
    return result


def summary_line(diff: Dict) -> str:
    parts = []
    for field, s in diff["fields"].items():
        parts.append(f"{field}: {'column missing' if s['missing'] else str(s['pct']) + '%'}")
    return "Words changed — " + " · ".join(parts)


def render_diff_md(diff: Dict, base_name: str) -> str:
    lines = [f"# {base_name} — DRAFT vs FINAL", "", summary_line(diff), "",
             f"Generated {date.today().isoformat()} by PFD.", ""]
    for field, s in diff["fields"].items():
        if s["missing"]:
            lines.append(f"- **{field}**: column not found in one of the files")
        else:
            lines.append(f"- **{field}**: {s['changed']} of {s['words']} draft words changed ({s['pct']}%)")
    if diff["unmatched"]:
        lines += ["", "## Tracks in DRAFT but not in FINAL", ""] + [f"- {t}" for t in diff["unmatched"]]
    if diff["tracks"]:
        lines += ["", "## Changes", ""]
        for c in diff["tracks"]:
            lines += [f"### {c['title']} — {c['field']}", "", f"DRAFT: {c['draft']}", "",
                      f"FINAL: {c['final']}", ""]
    return "\n".join(lines).rstrip() + "\n"


# ── Dropbox IO ─────────────────────────────────────────────────────────────────

def _overwrite():
    import dropbox
    return dropbox.files.WriteMode.overwrite


def write_draft(dbx, catalog: str, album_code: str, album: str, csv_bytes: bytes) -> str:
    path = capture_paths(catalog, album_code, album)["draft"]
    dbx.files_upload(csv_bytes, path, mode=_overwrite(), mute=True)
    return path


def export_album(dbx, app_data: Dict, catalog: str, album_code: str,
                 reference: Optional[List[str]] = None) -> Tuple[bytes, str, str]:
    """
    Build the ZIP and write the untouched DRAFT CSV to Dropbox in one step, so
    no export ever happens without its DRAFT. Returns (zip_bytes, zip_name, draft_path).
    """
    zip_bytes, zip_name = build_zip(app_data, catalog, album_code, reference)
    album = app_data.get("album_name_selected") or "album"
    draft_path = write_draft(dbx, catalog, album_code, album, build_csv(app_data, catalog, reference))
    return zip_bytes, zip_name, draft_path


def read_columns_reference(dbx) -> Optional[List[str]]:
    """Vesna's SourceAudio column list, or None when she has not placed it yet."""
    import dropbox
    try:
        _, resp = dbx.files_download(COLUMNS_REFERENCE_PATH)
    except dropbox.exceptions.ApiError as exc:
        if getattr(getattr(exc, "error", None), "is_path", lambda: False)():
            return None
        raise
    return parse_columns_reference(resp.content.decode("utf-8-sig")) or None


def find_draft(dbx, album_code: str) -> Optional[str]:
    """Path of the DRAFT CSV in an album folder, newest if several."""
    result = dbx.files_list_folder(album_folder(album_code))
    drafts = [e for e in result.entries if e.name.endswith("_DRAFT.csv")]
    if not drafts:
        return None
    drafts.sort(key=lambda e: getattr(e, "server_modified", None) or 0, reverse=True)
    return drafts[0].path_display


def save_final_and_diff(dbx, album_code: str, final_bytes: bytes) -> Dict[str, str]:
    """
    Save Vesna's FINAL next to the DRAFT and write the DIFF. Raises if there is
    no DRAFT for the album — a FINAL with nothing to compare against is a mistake
    the uploader needs to see.
    """
    draft_path = find_draft(dbx, album_code)
    if not draft_path:
        raise FileNotFoundError(f"No DRAFT CSV in {album_folder(album_code)}. Export the album first.")
    base = draft_path.rsplit("/", 1)[1][: -len("_DRAFT.csv")]
    folder = draft_path.rsplit("/", 1)[0]
    final_path, diff_path = f"{folder}/{base}_FINAL.csv", f"{folder}/{base}_DIFF.md"

    _, resp = dbx.files_download(draft_path)
    draft_df = pd.read_csv(io.BytesIO(resp.content))
    final_df = pd.read_csv(io.BytesIO(final_bytes))
    diff = compute_diff(draft_df, final_df)

    dbx.files_upload(final_bytes, final_path, mode=_overwrite(), mute=True)
    dbx.files_upload(render_diff_md(diff, base).encode("utf-8"), diff_path, mode=_overwrite(), mute=True)
    return {"final": final_path, "diff": diff_path, "summary": summary_line(diff)}


def write_writer_test(dbx, markdown: str, day: Optional[str] = None) -> str:
    import dropbox
    path = f"{TESTS_FOLDER}/writer_test_{day or date.today().isoformat()}.md"
    meta = dbx.files_upload(markdown.encode("utf-8"), path,
                            mode=dropbox.files.WriteMode.add, autorename=True, mute=True)
    return getattr(meta, "path_display", path)
