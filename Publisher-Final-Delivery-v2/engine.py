"""
Publisher Final Delivery App - Ingestion Engine v2
- Gemini 2.5 Pro: audio analysis only (Tab 01)
- Claude Sonnet: all writing tasks (Tabs 02-06)
- Dropbox: cloud folder access
- Manual refinement mode for fixing existing copy
"""
import os
import json
import time
import re
import io
import zipfile
import pandas as pd
import google.generativeai as genai
import anthropic
from pathlib import Path
from typing import List, Optional, Dict, Tuple
from prompts import PromptEngine

from google.api_core import retry
from google.api_core.exceptions import InternalServerError, ServiceUnavailable

# Latest models — update these strings when new versions release
GEMINI_AUDIO_MODEL = "gemini-3.1-pro-preview"
CLAUDE_WRITING_MODEL = "claude-sonnet-4-6"

DEFAULT_ROOT_PATH = Path(".")


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
        """List audio files in a Dropbox folder. Returns list of {name, path, size}."""
        try:
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            result = dbx.files_list_folder(folder_path)
            audio_files = []
            for entry in result.entries:
                if hasattr(entry, "size") and any(
                    entry.name.lower().endswith(ext) for ext in [".mp3", ".wav", ".aiff", ".flac"]
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
        """Download a file from Dropbox to a local temp path. Returns local path."""
        try:
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            dbx.files_download_to_file(local_path, file_path)
            return local_path
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {str(e)}")

    def upload_to_dropbox(self, dropbox_token: str, local_path: str, dropbox_dest: str):
        """Upload a file to Dropbox output folder."""
        try:
            import dropbox
            dbx = dropbox.Dropbox(dropbox_token)
            with open(local_path, "rb") as f:
                dbx.files_upload(f.read(), dropbox_dest, mute=True)
        except Exception as e:
            raise RuntimeError(f"Dropbox upload failed: {str(e)}")

    # ── Keyword Processing ─────────────────────────────────────────────────────
    def process_keywords(self, keywords_raw: str, catalog: str, gemini_api_key: str) -> str:
        """Enforce 3-word limit, Title Case, remove banned words."""
        if not keywords_raw:
            return ""
        kw_list = [k.strip() for k in re.split(r"[,;]", keywords_raw) if k.strip()]

        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel(GEMINI_AUDIO_MODEL)

        corrected = []
        for kw in kw_list:
            if kw.count(" ") > 2:
                prompt = self.prompts.get_harvest_loop_prompt(kw)
                try:
                    res = model.generate_content(prompt)
                    new_kw = res.text.strip()
                    corrected.append(new_kw if new_kw else kw)
                except Exception:
                    corrected.append(kw)
            else:
                corrected.append(kw)

        banned = {"epic", "huge", "massive", "awesome", "badass"}
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
                final.append(" ".join(parts[:3]).title() if len(parts) > 3 else kw.title())

        return ", ".join(final[:20])

    # ── Audio Analysis: GEMINI ONLY ────────────────────────────────────────────
    def analyze_audio_file(
        self, file_path: str, clean_title: str, catalog: str, gemini_api_key: str
    ) -> Optional[Dict]:
        """Analyze audio with Gemini. Returns raw metadata dict."""
        genai.configure(api_key=gemini_api_key)
        model = genai.GenerativeModel(GEMINI_AUDIO_MODEL)

        audio_file = genai.upload_file(path=file_path)
        while audio_file.state.name == "PROCESSING":
            time.sleep(2)
            audio_file = genai.get_file(audio_file.name)

        if audio_file.state.name != "ACTIVE":
            raise RuntimeError(
                f"Gemini file upload failed — state: '{audio_file.state.name}' for {file_path}"
            )

        analysis_prompt = self.prompts.generate_keywords_analysis_prompt(catalog, clean_title)

        retry_policy = retry.Retry(
            predicate=retry.if_exception_type(InternalServerError, ServiceUnavailable),
            initial=2.0,
            maximum=60.0,
            multiplier=2.0,
            timeout=600.0,
        )

        try:
            response = retry_policy(model.generate_content)(
                [analysis_prompt, audio_file],
                request_options={"timeout": 600},
            )
        finally:
            genai.delete_file(audio_file.name)

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
        self, system_instruction: str, prompt: str, claude_api_key: str, max_tokens: int = 1024
    ) -> str:
        """Invoke Claude for all writing tasks."""
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
        self, title: str, raw_desc: str, catalog: str, claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_track_description_prompt(
            title, raw_desc, catalog
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
        self, album_name: str, album_description: str, catalog: str,
        ref_urls: List[str], claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_cover_art_prompt(
            album_name, album_description, catalog, ref_urls
        )
        return self.call_claude(sys_instr, prompt, claude_api_key, max_tokens=2048)

    def generate_mailchimp_intro(
        self, album_name: str, album_description: str, catalog: str, claude_api_key: str
    ) -> str:
        sys_instr, prompt = self.prompts.generate_mailchimp_intro_prompt(
            album_name, album_description, catalog
        )
        return self.call_claude(sys_instr, prompt, claude_api_key)

    def manual_refinement(
        self, content: str, content_type: str, catalog: str, claude_api_key: str
    ) -> str:
        """Fix any existing bad copy — track desc, album desc, mailchimp, etc."""
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
    def validate_data(self, data: Dict) -> Tuple[bool, List[str]]:
        errors = []
        banned = {"epic", "huge", "massive", "awesome", "badass"}
        folder_path = self.folders.get("02_VOICE_GUIDES")
        if folder_path and folder_path.exists():
            banned_file = folder_path / "Banned_Keywords.txt"
            if banned_file.exists():
                text = banned_file.read_text(encoding="utf-8")
                banned.update([l.strip().lower() for l in text.splitlines() if l.strip()])

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
                first_word = re.sub(r"^\W+|\W+$", "", desc.split(" ")[0].lower())
                if first_word in ["a", "an", "the"]:
                    errors.append(
                        f"Track '{title}': description violates Antigravity Protocol (starts with '{first_word}')."
                    )

        album_desc = data.get("album_description", "").lower()
        if any(b in album_desc for b in banned):
            errors.append("Album Description contains a banned word.")

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
