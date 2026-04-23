"""
Publisher Final Delivery App - Ingestion Engine v2
- Gemini 3.1 Pro: audio analysis only (Tab 01)
- Claude Sonnet: all writing tasks (Tabs 02-06)
- Dropbox: cloud folder access
- Manual refinement mode for fixing existing copy

Tier 1 fixes applied:
- Migrated from deprecated google.generativeai to google.genai
- Added catalog contamination check to validator
- Expanded banned words list
- Always use latest Gemini model: gemini-3.1-pro-preview
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

# Latest models — always use the most current available
GEMINI_AUDIO_MODEL = "gemini-3.1-pro-preview"
CLAUDE_WRITING_MODEL = "claude-sonnet-4-6"

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

    # ── Dropbox Integration ────────────────────────────────────────────────────
    def list_dropbox_audio_files(self, dropbox_token: str, folder_path: str = "") -> List[Dict]:
        try:
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            result = dbx.files_list_folder(folder_path)
            audio_files = []
            for entry in result.entries:
                if hasattr(entry, "size") and any(
                    entry.name.lower().endswith(ext)
                    for ext in [".mp3", ".wav", ".aiff", ".flac"]
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
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            dbx.files_download_to_file(local_path, file_path)
            return local_path
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {str(e)}")

    def upload_to_dropbox(self, dropbox_token: str, local_path: str, dropbox_dest: str):
        try:
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            with open(local_path, "rb") as f:
                dbx.files_upload(f.read(), dropbox_dest, mute=True)
        except Exception as e:
            raise RuntimeError(f"Dropbox upload failed: {str(e)}")

    # ── Keyword Processing ─────────────────────────────────────────────────────
    def process_keywords(self, keywords_raw: str, catalog: str, gemini_api_key: str) -> str:
        if not keywords_raw:
            return ""
        kw_list = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

        client = genai.Client(api_key=gemini_api_key)

        corrected = []
        for kw in kw_list:
            if kw.count(" ") > 2:
                prompt = self.prompts.get_harvest_loop_prompt(kw)
                try:
                    response = client.models.generate_content(
                        model=GEMINI_AUDIO_MODEL,
                        contents=prompt,
                    )
                    new_kw = response.text.strip()
                    corrected.append(new_kw if new_kw else kw)
                except Exception:
                    corrected.append(kw)
            else:
                corrected.append(kw)

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
        for kw in corrected:
            kw_lower = kw.lower()
            words = set(kw_lower.split())
            if not any(b in words or b in kw_lower for b in banned):
                parts = kw_lower.split()
                final.append(
                    " ".join(parts[:3]).title() if len(parts) > 3 else kw.title()
                )

        return ", ".join(final[:20])

    # ── Audio Analysis: GEMINI ONLY ────────────────────────────────────────────
    def analyze_audio_file(
        self, file_path: str, clean_title: str, catalog: str, gemini_api_key: str
    ) -> Optional[Dict]:
        client = genai.Client(api_key=gemini_api_key)

        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".aiff": "audio/aiff",
            ".flac": "audio/flac",
        }
        mime_type = mime_map.get(ext, "audio/mpeg")

        with open(file_path, "rb") as f:
            file_bytes = f.read()

        uploaded_file = client.files.upload(
            file=io.BytesIO(file_bytes),
            config=types.UploadFileConfig(
                mime_type=mime_type,
                display_name=clean_title,
            ),
        )

        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = client.files.get(name=uploaded_file.name)

        if uploaded_file.state.name != "ACTIVE":
            raise RuntimeError(
                f"Gemini file upload failed — state: '{uploaded_file.state.name}' for {file_path}"
            )

        analysis_prompt = self.prompts.generate_keywords_analysis_prompt(catalog, clean_title)

        try:
            response = client.models.generate_content(
                model=GEMINI_AUDIO_MODEL,
                contents=[
                    types.Part.from_uri(
                        file_uri=uploaded_file.uri,
                        mime_type=mime_type,
                    ),
                    analysis_prompt,
                ],
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=600),
                ),
            )
        finally:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception:
                pass

        text = response.text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]

        metadata = json.loads(text.strip())
        if metadata.get("Keywords"):
            metadata["Keywords"] = self.process_keywords(
                metadata["Keywords"], catalog, gemini_api_key
            )
        return metadata

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
            return message.content[0].text.strip()
        except Exception as e:
            return f"Claude Error: {str(e)}"

    def refine_track_description(
        self, title: str, raw_desc: str, catalog: str, claude_api_key: str,
        mix_type: str = "unknown"
    ) -> str:
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
    def compile_final_package(self, data: Dict) -> io.BytesIO:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            if data.get("tracks"):
                df_kw = pd.DataFrame(data["tracks"])[["Title", "Keywords"]]
                zf.writestr("01 Track Keywords/Track_Keywords.csv", df_kw.to_csv(index=False))
                df_desc = pd.DataFrame(data["tracks"])[["Title", "Track Description"]]
                zf.writestr("02 Track Descriptions/Track_Descriptions.csv", df_desc.to_csv(index=False))
            zf.writestr("03 Album Description/Album_Description.txt", data.get("album_description", ""))
            zf.writestr("04 Album Name/Album_Name.txt", data.get("album_name", ""))
            zf.writestr("05 Album Cover Art/MidJourney_Prompts.txt", data.get("cover_art", ""))
            zf.writestr("06 MailChimp Intro/MailChimp_Copy.txt", data.get("mailchimp_intro", ""))
        zip_buffer.seek(0)
        return zip_buffer
