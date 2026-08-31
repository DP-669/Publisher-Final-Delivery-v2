"""
Publisher Final Delivery App - Ingestion Engine v2
- Gemini 3.1 Pro: audio analysis only (Tab 01)
- Claude Sonnet 5: all writing tasks (Tabs 02-06)
- Dropbox: cloud folder access
- Manual refinement mode for fixing existing copy

Tier 1 fixes applied:
- Migrated from deprecated google.generativeai to google.genai
- Added catalog contamination check to validator
- Expanded banned words list
- Always use latest Gemini model: gemini-3.1-pro-preview

Tier 2 fixes applied (2026-08-13):
- Updated Claude model to claude-sonnet-5
- Catalog normalizer added to prompts.py (fixes contamination from name variants)
- Tab 02 refinement prompt rewritten to preserve Gemini audio specifics

Tier 3 update (2026-08-13):
- Gemini now produces 6 fields per track (Overall Consensus, Trailer/Campaign Description,
  Editor Description, Supervisor Description, Keywords, Tip)
- synthesize_master_description(): Claude synthesizes all 6 into one definitive 3-sentence description
- compile_final_package(): single unified CSV containing all columns

Tier 4 update (2026-08-13):
- Dropbox Pipeline: automated album folder crawling, batch Gemini analysis
- Sound design element analysis: separate Gemini + Claude pipeline
- AIF file support added (.aif → audio/aiff)
- Quota/billing error detection: fires ntfy alert on Gemini quota exhaustion
"""
import os
import json
import time
import re
import io
import zipfile
import pandas as pd
import anthropic
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from prompts import PromptEngine

from google import genai
from google.genai import types

# ── Model pins ────────────────────────────────────────────────────────────────
# These are the models the app runs on. They are overridable from Streamlit
# secrets so a new model can be adopted without a code change or redeploy:
#
#   GEMINI_AUDIO_MODEL   = "gemini-3.4-pro"
#   CLAUDE_WRITING_MODEL = "claude-sonnet-6"
#
# models.py checks these against each provider's live list-models endpoint and
# reports anything newer. It never switches a pin on its own — see models.py.
DEFAULT_GEMINI_AUDIO_MODEL = "gemini-3.1-pro-preview"
DEFAULT_CLAUDE_WRITING_MODEL = "claude-sonnet-5"


def _pinned(key: str, default: str) -> str:
    """Read a model pin from Streamlit secrets, then env, else the default."""
    try:
        import streamlit as st
        value = st.secrets.get(key)
        if value:
            return str(value).strip()
    except Exception:
        pass
    return os.environ.get(key, default).strip() or default


GEMINI_AUDIO_MODEL = _pinned("GEMINI_AUDIO_MODEL", DEFAULT_GEMINI_AUDIO_MODEL)
CLAUDE_WRITING_MODEL = _pinned("CLAUDE_WRITING_MODEL", DEFAULT_CLAUDE_WRITING_MODEL)

DEFAULT_ROOT_PATH = Path(".")

# ── Placement territory rules ──────────────────────────────────────────────────
THEATRICAL_TERMS = {
    "trailer", "blockbuster", "theatrical", "cinematic film",
    "movie trailer", "trailer music", "modern trailer",
    "hollywood", "feature film", "imax"
}

COMMERCIAL_TERMS = {
    "advertising", "retail", "streetwear", "brand campaign",
    "consumer", "commercial campaign", "lifestyle advertising",
    "product launch", "tv commercial"
}

THEATRICAL_CATALOGS = {"redcola", "rc", "ssc", "short story collective"}
COMMERCIAL_CATALOGS = {"epp", "ekonomic propaganda"}

# ── Track data field names ─────────────────────────────────────────────────────
TRACK_FIELDS_BASE = ["Title", "Mix Type", "Overall Consensus", "Editor Description",
                     "Supervisor Description", "Keywords", "Tip", "Track Description"]

# ── MIME type map — includes both .aif and .aiff ──────────────────────────────
AUDIO_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".flac": "audio/flac",
}


def _is_quota_error(exc: Exception) -> bool:
    """Detect Gemini quota / billing exhaustion."""
    msg = str(exc).lower()
    return any(s in msg for s in [
        "quota", "resource_exhausted", "resourceexhausted",
        "billing", "insufficient", "exceeded", "rate limit", "429", "403",
    ])


class IngestionEngine:
    """Core engine: Gemini for audio, Claude for writing, Dropbox for cloud access."""

    def __init__(self, root_path: Optional[str] = None):
        self.root_path = Path(root_path) if root_path else DEFAULT_ROOT_PATH
        self.folders: Dict[str, Optional[Path]] = {
            "01_VISUAL_REFERENCES": None,
            "02_VOICE_GUIDES": None,
            "03_METADATA_MASTER": None,
        }
        self.prompts = PromptEngine(str(self.root_path))
        # Keywords the shortener could not process on the last process_keywords
        # call. Kept whole in the output and surfaced in the UI for review.
        self.keyword_warnings: List[Dict] = []
        if self.root_path.exists():
            self._resolve_subfolders()

    def set_root_path(self, root_path: str):
        self.root_path = Path(root_path)
        self.prompts = PromptEngine(str(self.root_path))
        if self.root_path.exists():
            self._resolve_subfolders()

    def _resolve_subfolders(self):
        try:
            subdirs = [d for d in self.root_path.iterdir() if d.is_dir()]
            for folder_key in self.folders.keys():
                match = next(
                    (d for d in subdirs if folder_key.lower() in d.name.lower()), None
                )
                self.folders[folder_key] = match
        except Exception as e:
            print(f"Error resolving subfolders: {e}")

    def _context_desc_label(self, catalog: str) -> str:
        """Returns 'Campaign Description' for EPP, 'Trailer Description' for rC/SSC."""
        from prompts import _normalize_catalog
        return "Campaign Description" if _normalize_catalog(catalog) == "EPP" else "Trailer Description"

    # ── Dropbox Integration ────────────────────────────────────────────────────
    def get_dropbox_client(self, dropbox_token: str = None):
        try:
            import dropbox as dbx_mod
            # Prefer refresh token auth (permanent) over short-lived access token
            try:
                import streamlit as st
                app_key       = st.secrets.get("DROPBOX_APP_KEY")
                app_secret    = st.secrets.get("DROPBOX_APP_SECRET")
                refresh_token = st.secrets.get("DROPBOX_REFRESH_TOKEN")
                if app_key and app_secret and refresh_token:
                    return dbx_mod.Dropbox(
                        oauth2_refresh_token=refresh_token,
                        app_key=app_key,
                        app_secret=app_secret,
                    )
            except Exception:
                pass
            # Fall back to access token
            if dropbox_token:
                return dbx_mod.Dropbox(dropbox_token)
            raise RuntimeError("No Dropbox credentials found in secrets.")
        except ImportError:
            raise RuntimeError("Dropbox SDK not installed. Run: pip install dropbox")

    def list_dropbox_audio_files(self, dropbox_token: str, folder_path: str = "") -> List[Dict]:
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            result = dbx.files_list_folder(folder_path)
            audio_files = []
            for entry in result.entries:
                if hasattr(entry, "size") and any(
                    entry.name.lower().endswith(ext)
                    for ext in [".mp3", ".wav", ".aif", ".aiff", ".flac"]
                ):
                    audio_files.append({
                        "name": entry.name,
                        "path": entry.path_lower,
                        "size": entry.size,
                    })
            return audio_files
        except ImportError:
            raise RuntimeError("Dropbox SDK not installed. Run: pip install dropbox")
        except Exception as e:
            raise RuntimeError(f"Dropbox connection failed: {str(e)}")

    def download_from_dropbox(self, dropbox_token: str, file_path: str, local_path: str) -> str:
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            dbx.files_download_to_file(local_path, file_path)
            return local_path
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {str(e)}")

    def download_bytes_from_dropbox(self, dropbox_token: str, file_path: str) -> bytes:
        """Download a Dropbox file and return raw bytes."""
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            _, response = dbx.files_download(file_path)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {str(e)}")

    def upload_to_dropbox(self, dropbox_token: str, local_path: str, dropbox_dest: str):
        try:
            import dropbox
            dbx = self.get_dropbox_client(dropbox_token)
            with open(local_path, "rb") as f:
                dbx.files_upload(f.read(), dropbox_dest, mute=True)
        except Exception as e:
            raise RuntimeError(f"Dropbox upload failed: {str(e)}")

    def upload_bytes_to_dropbox(self, dropbox_token: str, data: bytes, dropbox_dest: str):
        """Upload raw bytes to Dropbox."""
        try:
            import dropbox as dbx_mod
            client = self.get_dropbox_client(dropbox_token)
            client.files_upload(
                data, dropbox_dest,
                mode=dbx_mod.files.WriteMode.overwrite,
                mute=True,
            )
        except Exception as e:
            raise RuntimeError(f"Dropbox upload failed: {str(e)}")

    # ── Keyword Processing ─────────────────────────────────────────────────────
    def process_keywords(self, keywords_raw: str, catalog: str, gemini_api_key: str) -> str:
        if not keywords_raw:
            return ""
        kw_list = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

        client = genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))

        # (keyword, keep_whole). keep_whole marks a phrase the shortener never
        # got to — it is kept intact rather than chopped to its first three
        # words, which would ship a fragment like "End Of The".
        corrected = []
        self.keyword_warnings = []
        for kw in kw_list:
            if kw.count(" ") > 2:
                prompt = self.prompts.get_harvest_loop_prompt(kw)
                try:
                    response = client.models.generate_content(
                        model=GEMINI_AUDIO_MODEL,
                        contents=prompt,
                    )
                    new_kw = response.text.strip()
                    corrected.append((new_kw, False) if new_kw else (kw, True))
                    if not new_kw:
                        self.keyword_warnings.append(
                            {"keyword": kw, "reason": "Shortener returned nothing"}
                        )
                except Exception as exc:
                    corrected.append((kw, True))
                    self.keyword_warnings.append(
                        {"keyword": kw, "reason": f"{type(exc).__name__}: {exc}"}
                    )
            else:
                corrected.append((kw, False))

        banned = {
            "epic", "huge", "massive", "awesome", "badass",
            "relentless", "explosive", "immense", "stunning",
            "breathtaking", "unleashing", "groundbreaking",
        }
        folder_path = self.folders.get("02_VOICE_GUIDES")
        if folder_path and folder_path.exists():
            banned_file = folder_path / "Banned_Keywords.txt"
            if banned_file.exists():
                text = banned_file.read_text(encoding="utf-8")
                banned.update([l.strip().lower() for l in text.splitlines() if l.strip()])

        final = []
        for kw, keep_whole in corrected:
            kw_lower = kw.lower()
            words = set(kw_lower.split())
            if not any(b in words or b in kw_lower for b in banned):
                parts = kw_lower.split()
                if len(parts) > 3 and not keep_whole:
                    final.append(" ".join(parts[:3]).title())
                else:
                    final.append(kw.title())

        if self.keyword_warnings:
            self._alert_keyword_warnings(catalog)

        return ", ".join(final[:20])

    def _alert_keyword_warnings(self, catalog: str):
        """
        Tell a human that a keyword came through unshortened.

        These are kept whole and delivered, so nothing is lost — but they were
        never reviewed by the shortener, so Damir or Vesna should eyeball them.
        Fire-and-forget: a failed alert must never break an album run.
        """
        try:
            from dropbox_pipeline import send_ntfy
            lines = "\n".join(
                f"- {w['keyword']}  ({w['reason']})" for w in self.keyword_warnings
            )
            send_ntfy(
                "PFD - keywords not shortened",
                f"Catalog: {catalog}\nKept whole and delivered as-is. Please review:\n{lines}",
            )
        except Exception:
            pass

    # ── Core Gemini upload helper ──────────────────────────────────────────────
    def _upload_to_gemini(self, file_bytes: bytes, ext: str, display_name: str, client):
        """Upload bytes to Gemini Files API and wait for ACTIVE state."""
        mime_type = AUDIO_MIME_MAP.get(ext.lower(), "audio/wav")
        uploaded_file = client.files.upload(
            file=io.BytesIO(file_bytes),
            config=types.UploadFileConfig(
                mime_type=mime_type,
                display_name=display_name,
            ),
        )
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)
        if uploaded_file.state.name != "ACTIVE":
            raise RuntimeError(
                f"Gemini file upload failed — state: '{uploaded_file.state.name}' for {display_name}"
            )
        return uploaded_file

    # ── Audio Analysis: GEMINI ONLY ────────────────────────────────────────────
    def analyze_audio_file(
        self, file_path: str, clean_title: str, catalog: str, gemini_api_key: str
    ) -> Optional[Dict]:
        """Analyze a music track (full or sparse mix). Returns 6-field dict."""
        client = genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))
        ext = os.path.splitext(file_path)[1].lower()
        mime_type = AUDIO_MIME_MAP.get(ext, "audio/mpeg")

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        analysis_prompt = self.prompts.generate_keywords_analysis_prompt(catalog, clean_title)

        try:
            response = client.models.generate_content(
                model=GEMINI_AUDIO_MODEL,
                contents=[
                    types.Part(inline_data=types.Blob(mime_type=mime_type, data=file_bytes)),
                    analysis_prompt,
                ],
            )
        except Exception as exc:
            if _is_quota_error(exc):
                from dropbox_pipeline import send_ntfy
                send_ntfy(
                    "⚠️ PFD — Gemini quota error",
                    f"Pipeline paused: {exc}\nTrack: {clean_title}",
                    priority="urgent",
                )
            raise

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]

        metadata = json.loads(text.strip())

        # Normalise context description to a single key
        context_label = self._context_desc_label(catalog)
        for raw_key in ("Trailer_Description", "Campaign_Description",
                        "Trailer Description", "Campaign Description"):
            if raw_key in metadata:
                metadata[context_label] = metadata.pop(raw_key)
                break

        # Normalise underscore keys to space keys
        for us_key, sp_key in (
            ("Overall_Consensus", "Overall Consensus"),
            ("Editor_Description", "Editor Description"),
            ("Supervisor_Description", "Supervisor Description"),
        ):
            if us_key in metadata:
                metadata[sp_key] = metadata.pop(us_key)

        if metadata.get("Keywords"):
            metadata["Keywords"] = self.process_keywords(
                metadata["Keywords"], catalog, gemini_api_key
            )
        return metadata

    def analyze_audio_bytes(
        self, file_bytes: bytes, ext: str, clean_title: str, catalog: str, gemini_api_key: str
    ) -> Optional[Dict]:
        """Analyze audio from bytes (used by pipeline after Dropbox download)."""
        import tempfile
        tmp_path = f"/tmp/{clean_title}{ext}"
        try:
            with open(tmp_path, "wb") as f:
                f.write(file_bytes)
            return self.analyze_audio_file(tmp_path, clean_title, catalog, gemini_api_key)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    # ── Sound Design Analysis ──────────────────────────────────────────────────
    def analyze_sound_design_element(
        self, file_bytes: bytes, ext: str, element_name: str, gemini_api_key: str
    ) -> Optional[Dict]:
        """Analyze a sound design element. Returns focused SDE metadata dict."""
        client = genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))
        mime_type = AUDIO_MIME_MAP.get(ext.lower(), "audio/mpeg")
        analysis_prompt = self.prompts.generate_sound_design_analysis_prompt(element_name)

        try:
            response = client.models.generate_content(
                model=GEMINI_AUDIO_MODEL,
                contents=[
                    types.Part(inline_data=types.Blob(mime_type=mime_type, data=file_bytes)),
                    analysis_prompt,
                ],
            )
        except Exception as exc:
            if _is_quota_error(exc):
                from dropbox_pipeline import send_ntfy
                send_ntfy(
                    "⚠️ PFD — Gemini quota error",
                    f"Pipeline paused on sound design: {exc}\nElement: {element_name}",
                    priority="urgent",
                )
            raise

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return {"Element_Type": "Unknown", "Sonic_Character": text, "Keywords": ""}

    def synthesize_sound_design_description(
        self, element_name: str, parent_track: str, gemini_data: dict, claude_api_key: str
    ) -> str:
        """Claude writes the final 2-3 sentence description for a sound design element."""
        sys_instr, prompt = self.prompts.generate_sound_design_description_prompt(
            element_name, parent_track, gemini_data
        )
        return self.call_claude(sys_instr, prompt, claude_api_key, max_tokens=512)

    # ── Writing Tasks: CLAUDE ONLY ─────────────────────────────────────────────
    def call_claude(
        self,
        system_instruction: str,
        prompt: str,
        claude_api_key: str,
        max_tokens: int = 1024,
    ) -> str:
        client = anthropic.Anthropic(api_key=claude_api_key)
        try:
            message = client.messages.create(
                model=CLAUDE_WRITING_MODEL,
                max_tokens=max_tokens,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt}],
            )
            # claude-sonnet-5 may return ThinkingBlock objects before text.
            # Always extract from the first block with a .text attribute.
            for block in message.content:
                if hasattr(block, "text"):
                    return block.text.strip()
            return ""
        except Exception as e:
            return f"Claude Error: {str(e)}"

    def synthesize_master_description(
        self, title: str, track_data: dict, catalog: str, claude_api_key: str,
        mix_type: str = "unknown", is_redo: bool = False, user_guidance: str = ""
    ) -> str:
        """Tab 02 — synthesize all 6 Gemini fields into one definitive 3-sentence description."""
        sys_instr, prompt = self.prompts.generate_master_description_prompt(
            title, track_data, catalog, mix_type=mix_type,
            is_redo=is_redo, user_guidance=user_guidance
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def refine_track_description(
        self, title: str, raw_desc: str, catalog: str, claude_api_key: str,
        mix_type: str = "unknown"
    ) -> str:
        """Legacy single-description refinement. Used by Tab 07 manual refinement."""
        sys_instr, prompt = self.prompts.generate_track_description_prompt(
            title, raw_desc, catalog, mix_type=mix_type
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def generate_album_description(
        self, track_descriptions: List[str], catalog: str, claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_album_description_prompt(
            track_descriptions, catalog
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def generate_album_description_iteration(
        self,
        track_descriptions: List[str],
        catalog: str,
        iteration_history: List[Dict],
        user_guidance: str,
        claude_api_key: str,
    ) -> str:
        """Iterative refinement of the album description with conversation history."""
        sys_instr, prompt = self.prompts.generate_album_description_iteration_prompt(
            track_descriptions, catalog, iteration_history, user_guidance
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def generate_album_names(
        self, album_description: str, catalog: str, claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_album_name_prompt(
            album_description, catalog
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def generate_cover_art_prompts(
        self,
        album_name: str,
        album_description: str,
        catalog: str,
        ref_urls: List[str],
        claude_api_key: str,
        track_descriptions: List[str] = None,
        keywords: str = None,
    ) -> str:
        sys_instr, prompt = self.prompts.generate_cover_art_prompt(
            album_name, album_description, catalog, ref_urls,
            track_descriptions=track_descriptions,
            keywords=keywords,
        )
        return self.call_claude(sys_instr, prompt, claude_api_key, max_tokens=2048)

    def generate_mailchimp_intro(
        self,
        album_name: str,
        album_description: str,
        catalog: str,
        claude_api_key: str,
        track_descriptions: List[str] = None,
    ) -> str:
        sys_instr, prompt = self.prompts.generate_mailchimp_intro_prompt(
            album_name, album_description, catalog,
            track_descriptions=track_descriptions,
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def manual_refinement(
        self, content: str, content_type: str, catalog: str, claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_manual_refinement_prompt(
            content, content_type, catalog
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    # ── Metadata helper ────────────────────────────────────────────────────────
    def get_metadata_df(self, catalog: Optional[str] = None) -> Optional[pd.DataFrame]:
        folder_path = self.folders.get("03_METADATA_MASTER")
        if not folder_path or not folder_path.exists():
            return None
        try:
            csv_files = list(folder_path.glob("*.csv"))
            if catalog:
                csv_files = [f for f in csv_files if catalog.lower() in f.name.lower()]
            if not csv_files:
                return None
            dfs = []
            for fp in csv_files:
                try:
                    dfs.append(pd.read_csv(fp))
                except Exception:
                    pass
            return pd.concat(dfs, ignore_index=True) if dfs else None
        except Exception:
            return None

    # ── Clean Room Validator ───────────────────────────────────────────────────
    def validate_data(self, data: Dict, catalog: str = "") -> Tuple[bool, List[str]]:
        errors = []

        banned = {
            "epic", "huge", "massive", "awesome", "badass",
            "relentless", "explosive", "immense", "stunning",
            "breathtaking", "unleashing", "groundbreaking",
        }
        folder_path = self.folders.get("02_VOICE_GUIDES")
        if folder_path and folder_path.exists():
            banned_file = folder_path / "Banned_Keywords.txt"
            if banned_file.exists():
                text = banned_file.read_text(encoding="utf-8")
                banned.update([l.strip().lower() for l in text.splitlines() if l.strip()])

        catalog_lower = catalog.lower()
        is_theatrical = any(c in catalog_lower for c in THEATRICAL_CATALOGS)
        is_commercial = any(c in catalog_lower for c in COMMERCIAL_CATALOGS)

        tracks = data.get("tracks", [])
        for i, track in enumerate(tracks):
            title = track.get("Title", f"Track {i+1}")

            kw_str = track.get("Keywords", "")
            if kw_str:
                for kw in kw_str.split(","):
                    kw = kw.strip()
                    if kw.count(" ") > 2:
                        errors.append(f"Track '{title}': keyword '{kw}' exceeds 3 words.")
                    if any(b in kw.lower() for b in banned):
                        errors.append(f"Track '{title}': keyword '{kw}' contains a banned word.")

            desc = track.get("Track Description", "").strip()
            if desc:
                desc_lower = desc.lower()
                first_word = re.sub(r"^\W+|\W+$", "", desc.split(" ")[0].lower())
                if first_word in ["a", "an", "the"]:
                    errors.append(
                        f"Track '{title}': description violates Antigravity Protocol "
                        f"(starts with '{first_word}')."
                    )
                if is_commercial:
                    found = [t for t in THEATRICAL_TERMS if t in desc_lower]
                    if found:
                        errors.append(
                            f"Track '{title}': EPP description contains theatrical language "
                            f"({', '.join(found)}). EPP is commercial catalog only."
                        )
                if is_theatrical:
                    found = [t for t in COMMERCIAL_TERMS if t in desc_lower]
                    if found:
                        errors.append(
                            f"Track '{title}': {catalog} description contains commercial language "
                            f"({', '.join(found)}). {catalog} is theatrical/broadcast only."
                        )

        album_desc = data.get("album_description", "").lower()
        if any(b in album_desc for b in banned):
            errors.append("Album Description contains a banned word.")
        if is_commercial and any(t in album_desc for t in THEATRICAL_TERMS):
            errors.append("Album Description contains theatrical language — invalid for EPP.")
        if is_theatrical and any(t in album_desc for t in COMMERCIAL_TERMS):
            errors.append(f"Album Description contains commercial language — invalid for {catalog}.")

        album_name = data.get("album_name", "").lower()
        if any(b in album_name for b in banned):
            errors.append("Album Name contains a banned word.")

        if not tracks:
            errors.append("No track data found to export.")

        return len(errors) == 0, errors

    # ── ZIP Compiler ───────────────────────────────────────────────────────────
    def compile_final_package(self, data: Dict, catalog: str = "") -> io.BytesIO:
        """
        Single unified CSV with all track columns + separate text files for album assets.
        Column order: Title, Mix Type, Track Description (Master), Overall Consensus,
        Trailer/Campaign Description, Editor Description, Supervisor Description, Keywords, Tip
        """
        context_label = self._context_desc_label(catalog) if catalog else "Trailer Description"

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if data.get("tracks"):
                tracks = data["tracks"]
                rows = []
                for t in tracks:
                    rows.append({
                        "Title": t.get("Title", ""),
                        "Mix Type": t.get("Mix Type", ""),
                        "Track Description": t.get("Track Description", ""),
                        "Overall Consensus": t.get("Overall Consensus", ""),
                        context_label: t.get(context_label, ""),
                        "Editor Description": t.get("Editor Description", ""),
                        "Supervisor Description": t.get("Supervisor Description", ""),
                        "Keywords": t.get("Keywords", ""),
                        "Tip": t.get("Tip", ""),
                    })
                df = pd.DataFrame(rows)
                zf.writestr("Track_Data.csv", df.to_csv(index=False))

            zf.writestr("Album_Description.txt", data.get("album_description", ""))
            zf.writestr("Album_Name.txt", data.get("album_name_selected") or data.get("album_name", ""))
            zf.writestr("MidJourney_Prompts.txt", data.get("cover_art", ""))
            zf.writestr("MailChimp_Copy.txt", data.get("mailchimp_intro", ""))

        zip_buffer.seek(0)
        return zip_buffer
