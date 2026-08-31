"""
Dropbox Pipeline — automated album folder crawling and file categorization.
Supports rC (numbered folders), SSC (organic naming), EPP (cutdowns).
"""

import os
from dataclasses import dataclass, field
from typing import List

NTFY_TOPIC = "Damir-rMG-2026"
AUDIO_EXTENSIONS = {".wav", ".aif", ".aiff", ".mp3", ".flac"}
BATCH_SIZE = 3


def send_ntfy(title: str, body: str, priority: str = "default"):
    """Fire-and-forget ntfy notification."""
    try:
        import requests
        requests.post(
            f"https://ntfy.sh/{NTFY_TOPIC}",
            data=body.encode("utf-8"),
            headers={"Title": title, "Priority": priority},
            timeout=10,
        )
    except Exception:
        pass


def detect_catalog_from_path(path: str) -> str:
    """Auto-detect catalog from Dropbox path. Returns 'redCola', 'SSC', or 'EPP'."""
    p = path.lower()
    if "redcola" in p or "01 redcola" in p:
        return "redCola"
    if "short story" in p or "02 short story" in p:
        return "SSC"
    if "ekonomic" in p or "03 ekonomic" in p:
        return "EPP"
    return "unknown"


def is_quality_checked(path: str) -> bool:
    """True if the path is in a quality-checked folder, not WIP."""
    p = path.lower()
    return "passed quality" in p or "quality check" in p


def _is_audio(name: str) -> bool:
    return os.path.splitext(name.lower())[1] in AUDIO_EXTENSIONS


def categorize_folder(name: str) -> str:
    """
    Map a folder or file name to a track category.
    Returns: full_mix | sparse_mix | alt_mix | sound_design | cutdown | stems | unknown
    """
    n = name.lower()
    # Stems — always skip
    if any(x in n for x in ["stem", "detailed stem", "compact stem"]):
        return "stems"
    # Sound design elements
    if any(x in n for x in ["sound design", "04 sound", " elements"]):
        return "sound_design"
    # Cutdowns (EPP)
    if any(x in n for x in [":60", ":30", ":15", "cutdown", "cut down", "sting"]):
        return "cutdown"
    # Alt mixes (check before sparse/full to avoid false positives)
    if any(x in n for x in ["03 alt", "alt mix", "alt master", "alt version"]):
        return "alt_mix"
    # Sparse mixes (check before full)
    if any(x in n for x in ["02 sparse", "sparse", "sparce"]):
        return "sparse_mix"
    # Full mix
    if any(x in n for x in ["01 full", "full mix", "full master"]):
        return "full_mix"
    # SSC organic naming: folder ends with " mix" or " master" = full mix
    if n.endswith(" mix") or n.endswith(" master"):
        return "full_mix"
    return "unknown"


def _parse_omitted(name: str) -> str:
    """Infer omitted elements from alt mix folder name."""
    n = name.lower()
    if "no string" in n: return "Strings removed"
    if "no vocal" in n or "no vox" in n: return "Vocals removed"
    if "no perc" in n: return "Percussion removed"
    if "no brass" in n: return "Brass removed"
    if "bass and perc" in n or "bass & perc" in n: return "Bass and percussion only"
    return name  # Fall back to folder name


def _parse_duration(name: str) -> str:
    """Extract duration label from cutdown folder name."""
    n = name.lower()
    if "60" in n: return ":60"
    if "30" in n: return ":30"
    if "15" in n: return ":15"
    if "sting" in n: return "sting"
    return name


def _clean_title(filename: str) -> str:
    return os.path.splitext(filename)[0].strip()


@dataclass
class FileEntry:
    display_name: str   # Track/element display name
    dropbox_path: str   # Dropbox file path (lowercase)
    file_id: str        # Dropbox file ID
    size: int           # File size in bytes
    category: str       # full_mix | sparse_mix | alt_mix | sound_design | cutdown
    parent_track: str   # Track folder name this file belongs to
    mix_type: str       # "full" | "sparse" | "alt" | "sound_design" | "cutdown_:60" etc.
    notes: str = ""     # Alt mix: omitted elements. Cutdown: duration.


@dataclass
class CrawlResult:
    album_name: str
    catalog: str
    album_path: str
    entries: List[FileEntry] = field(default_factory=list)
    skipped: List[str] = field(default_factory=list)
    log: List[str] = field(default_factory=list)

    @property
    def analyzable(self) -> List[FileEntry]:
        """Files requiring Gemini audio analysis."""
        return [e for e in self.entries if e.category in ("full_mix", "sparse_mix", "sound_design")]

    @property
    def auto_described(self) -> List[FileEntry]:
        """Files that get template descriptions (no Gemini needed)."""
        return [e for e in self.entries if e.category in ("alt_mix", "cutdown")]

    def summary(self) -> str:
        cats: dict = {}
        for e in self.entries:
            cats[e.category] = cats.get(e.category, 0) + 1
        return " | ".join(f"{v} {k.replace('_', ' ')}" for k, v in cats.items())


# ── Dropbox helpers ────────────────────────────────────────────────────────────

def _list_folder(dbx, path: str) -> list:
    try:
        import dropbox as dbx_mod
        r = dbx.files_list_folder(path)
        items = list(r.entries)
        while r.has_more:
            r = dbx.files_list_folder_continue(r.cursor)
            items.extend(r.entries)
        return items
    except Exception:
        return []


def _find_primary_audio(dbx, folder_path: str):
    """Find the best audio file in a folder. Prefers mastered, then largest."""
    try:
        import dropbox as dbx_mod
        entries = _list_folder(dbx, folder_path)
        audio = [e for e in entries
                 if isinstance(e, dbx_mod.files.FileMetadata) and _is_audio(e.name)]
        if not audio:
            return None
        masters = [f for f in audio if "master" in f.name.lower()]
        return max(masters, key=lambda f: f.size) if masters else max(audio, key=lambda f: f.size)
    except Exception:
        return None


def resolve_shared_link(dbx, url: str) -> str:
    """Resolve a Dropbox shared link URL to a Dropbox file path."""
    try:
        meta = dbx.sharing_get_shared_link_metadata(url)
        return meta.path_lower
    except Exception as e:
        raise RuntimeError(f"Could not resolve Dropbox link: {e}")


# ── Crawl logic ────────────────────────────────────────────────────────────────

def crawl_album_folder(dbx, album_path: str, catalog: str) -> CrawlResult:
    """Crawl album folder structure and return categorized file list."""
    try:
        import dropbox as dbx_mod
    except ImportError:
        raise RuntimeError("Dropbox SDK not installed.")

    album_name = album_path.rstrip("/").split("/")[-1]
    result = CrawlResult(album_name=album_name, catalog=catalog, album_path=album_path)

    top_entries = _list_folder(dbx, album_path)
    if not top_entries:
        result.log.append("❌ Could not list album folder")
        return result

    track_folders = [e for e in top_entries if isinstance(e, dbx_mod.files.FolderMetadata)]
    result.log.append(f"📁 {len(track_folders)} track folders found")

    for tf in sorted(track_folders, key=lambda e: e.name):
        _process_track_folder(dbx, tf.path_lower, tf.name, result)

    return result


def _process_track_folder(dbx, track_path: str, track_name: str, result: CrawlResult):
    try:
        import dropbox as dbx_mod
    except ImportError:
        return

    entries = _list_folder(dbx, track_path)
    if not entries:
        result.log.append(f"  ⚠️ Empty or inaccessible: {track_name}")
        return

    result.log.append(f"  🎵 {track_name}")

    for e in entries:
        if isinstance(e, dbx_mod.files.FolderMetadata):
            cat = categorize_folder(e.name)

            if cat == "stems":
                result.skipped.append(f"{track_name}/{e.name}")
                continue

            if cat == "sound_design":
                _collect_sound_design(dbx, e.path_lower, track_name, result)
                continue

            if cat in ("full_mix", "sparse_mix"):
                af = _find_primary_audio(dbx, e.path_lower)
                if af:
                    result.entries.append(FileEntry(
                        display_name=_clean_title(af.name),
                        dropbox_path=af.path_lower,
                        file_id=af.id,
                        size=af.size,
                        category=cat,
                        parent_track=track_name,
                        mix_type="full" if cat == "full_mix" else "sparse",
                    ))
                    result.log.append(f"    ✓ {cat}: {af.name}")
                else:
                    result.log.append(f"    ⚠️ No audio file in {e.name}")
                    result.skipped.append(f"{track_name}/{e.name}")
                continue

            if cat == "alt_mix":
                af = _find_primary_audio(dbx, e.path_lower)
                if af:
                    result.entries.append(FileEntry(
                        display_name=_clean_title(af.name),
                        dropbox_path=af.path_lower,
                        file_id=af.id,
                        size=af.size,
                        category="alt_mix",
                        parent_track=track_name,
                        mix_type="alt",
                        notes=_parse_omitted(e.name),
                    ))
                    result.log.append(f"    ✓ alt_mix: {e.name}")
                continue

            if cat == "cutdown":
                af = _find_primary_audio(dbx, e.path_lower)
                dur = _parse_duration(e.name)
                if af:
                    result.entries.append(FileEntry(
                        display_name=_clean_title(af.name),
                        dropbox_path=af.path_lower,
                        file_id=af.id,
                        size=af.size,
                        category="cutdown",
                        parent_track=track_name,
                        mix_type=f"cutdown_{dur}",
                        notes=dur,
                    ))
                    result.log.append(f"    ✓ cutdown {dur}: {e.name}")
                continue

            # Unknown folder
            result.log.append(f"    ⚠️ Unrecognized: {e.name}")
            result.skipped.append(f"{track_name}/{e.name}")

        elif isinstance(e, dbx_mod.files.FileMetadata) and _is_audio(e.name):
            # Direct audio file in track folder (non-compliant delivery)
            cat = categorize_folder(e.name)
            if cat in ("unknown", "stems"):
                cat = "full_mix"
            result.entries.append(FileEntry(
                display_name=_clean_title(e.name),
                dropbox_path=e.path_lower,
                file_id=e.id,
                size=e.size,
                category=cat,
                parent_track=track_name,
                mix_type="full" if cat == "full_mix" else "sparse" if cat == "sparse_mix" else "alt",
            ))
            result.log.append(f"    ✓ direct file: {e.name} → {cat}")


def _collect_sound_design(dbx, folder_path: str, track_name: str, result: CrawlResult):
    """Collect all audio files from a Sound Design Elements folder."""
    try:
        import dropbox as dbx_mod
    except ImportError:
        return

    entries = _list_folder(dbx, folder_path)
    count = 0
    for e in entries:
        if isinstance(e, dbx_mod.files.FileMetadata) and _is_audio(e.name):
            result.entries.append(FileEntry(
                display_name=_clean_title(e.name),
                dropbox_path=e.path_lower,
                file_id=e.id,
                size=e.size,
                category="sound_design",
                parent_track=track_name,
                mix_type="sound_design",
            ))
            count += 1
    result.log.append(f"    ✓ sound_design: {count} elements")


# ── Batch helpers ──────────────────────────────────────────────────────────────

def is_quota_error(exc: Exception) -> bool:
    """Detect Gemini quota / billing exhaustion errors."""
    msg = str(exc).lower()
    quota_signals = [
        "quota", "resource_exhausted", "resourceexhausted",
        "billing", "insufficient", "exceeded", "rate limit",
        "429", "403",
    ]
    return any(s in msg for s in quota_signals)


def make_batches(entries: List[FileEntry], size: int = BATCH_SIZE) -> List[List[FileEntry]]:
    return [entries[i:i + size] for i in range(0, len(entries), size)]


def generate_alt_description(parent_track: str, notes: str) -> str:
    """Simple description for alt mixes — no Gemini needed."""
    if notes and notes != parent_track:
        return f"Alternate mix of {parent_track}. {notes}."
    return f"Alternate mix of {parent_track}."


def generate_cutdown_description(parent_track: str, duration: str) -> str:
    """Simple description for EPP cutdowns."""
    if duration.startswith(":"):
        return f"{duration} cutdown of {parent_track}."
    if duration == "sting":
        return f"Short sting excerpt from {parent_track} for transitions or outros."
    return f"Cutdown of {parent_track} ({duration})."
