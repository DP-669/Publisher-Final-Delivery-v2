"""
Publisher Final Delivery — engine (v3).

- Gemini: audio analysis behind the hallucination gate (gate.py). The analysis
  call receives audio bytes, the mix type and the catalog's rules — never the
  title, album, composer or filename. The title is joined afterwards, here.
- Claude: track-description gating/editing (per `track_writer`), album
  description, names, lane proposal, MailChimp, cover-art prompts.
- Every model call's system prompt is rules.system_instruction(catalog).
- Dropbox: folder access and capture. Nothing writes to Google Drive.
"""
import io
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import anthropic
from google import genai
from google.genai import types

import capture
import gate
import rules
from pfd_errors import report
from prompts import PromptEngine

log = logging.getLogger("pfd")

# ── Model pins ────────────────────────────────────────────────────────────────
# v3 resolves the newest Opus / newest Pro at runtime (models.resolve). These
# pins are the fallback when that check fails. Setting GEMINI_AUDIO_MODEL or
# CLAUDE_WRITING_MODEL in Streamlit secrets (or env) locks the model instead.
DEFAULT_GEMINI_AUDIO_MODEL = "gemini-3.1-pro-preview"
DEFAULT_CLAUDE_WRITING_MODEL = "claude-sonnet-5"


def _secret_value(key: str) -> Optional[str]:
    """Streamlit secrets, then env. None when neither is set."""
    try:
        import streamlit as st
        value = st.secrets.get(key)
        if value:
            return str(value).strip()
    except Exception as exc:  # no secrets.toml on this machine is normal; env is the fallback
        log.debug("Streamlit secrets unavailable for %s: %s", key, exc)
    value = (os.environ.get(key) or "").strip()
    return value or None


GEMINI_PIN_EXPLICIT = _secret_value("GEMINI_AUDIO_MODEL") is not None
CLAUDE_PIN_EXPLICIT = _secret_value("CLAUDE_WRITING_MODEL") is not None
GEMINI_AUDIO_MODEL = _secret_value("GEMINI_AUDIO_MODEL") or DEFAULT_GEMINI_AUDIO_MODEL
CLAUDE_WRITING_MODEL = _secret_value("CLAUDE_WRITING_MODEL") or DEFAULT_CLAUDE_WRITING_MODEL

DEFAULT_ROOT_PATH = Path(".")
REFERENCE_DIR = Path(__file__).resolve().parent / "reference"
RECENT_ALBUMS_PATH = REFERENCE_DIR / "recent_album_descriptions.json"

WRITER_MODES = ("gemini", "claude_synth", "claude_edit")

AUDIO_MIME_MAP = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".aif": "audio/aiff",
    ".aiff": "audio/aiff",
    ".flac": "audio/flac",
}

MIX_SUFFIX_PATTERNS = [
    r'[\s_-]+sparce?\s+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_-]+full\s+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_-]+alt(?:ernate)?\s+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_-]+trailer\s+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_-]+tv\s+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_-]+cut[\s_-]*down(?:[\s_]\d+)?$',
    r'[\s_-]+sound[\s_-]*design(?:[\s_]\d+)?$',
    r'[\s_-]+(?:sde|element)(?:[\s_]\d+)?$',
    r'[\s_-]+(?:mix|master)(?:[\s_]\d+)?$',
    r'[\s_]+\d+$',
]


class ClaudeError(RuntimeError):
    """A Claude call failed or returned nothing usable."""


def base_title(title: str) -> str:
    """'Lethal Night Sparse Mix' -> 'Lethal Night'."""
    name = title or ""
    for pat in MIX_SUFFIX_PATTERNS:
        cleaned = re.sub(pat, "", name, flags=re.IGNORECASE).strip()
        if cleaned and cleaned != name:
            return cleaned
    return name


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in [
        "quota", "resource_exhausted", "resourceexhausted",
        "billing", "insufficient", "exceeded", "rate limit", "429", "403",
    ])


def recent_album_descriptions(catalog: str) -> List[Dict]:
    """The catalog's last ten album descriptions, seeded from master metadata."""
    if not RECENT_ALBUMS_PATH.exists():
        return []
    data = json.loads(RECENT_ALBUMS_PATH.read_text(encoding="utf-8"))
    return (data.get(rules.catalog_code(catalog)) or [])[:10]


class IngestionEngine:
    def __init__(self, root_path: Optional[str] = None):
        self.root_path = Path(root_path) if root_path else DEFAULT_ROOT_PATH
        self.folders: Dict[str, Optional[Path]] = {"01_VISUAL_REFERENCES": None, "02_VOICE_GUIDES": None}
        self.prompts = PromptEngine()
        # Keywords the shortener could not process on the last process_keywords
        # call. Kept whole in the output and surfaced in the UI for review.
        self.keyword_warnings: List[Dict] = []
        self.gemini_model = GEMINI_AUDIO_MODEL
        self.claude_model = CLAUDE_WRITING_MODEL
        if self.root_path.exists():
            self._resolve_subfolders()

    def set_root_path(self, root_path: str):
        self.root_path = Path(root_path)
        if self.root_path.exists():
            self._resolve_subfolders()

    def _resolve_subfolders(self):
        try:
            subdirs = [d for d in self.root_path.iterdir() if d.is_dir()]
        except OSError as exc:
            report("Could not read the app folder", exc)
            return
        for key in self.folders:
            self.folders[key] = next((d for d in subdirs if key.lower() in d.name.lower()), None)

    def _context_desc_label(self, catalog: str) -> str:
        return capture.context_label(catalog)

    # ── Dropbox ────────────────────────────────────────────────────────────────
    def get_dropbox_client(self, dropbox_token: str = None):
        try:
            import dropbox as dbx_mod
        except ImportError:
            raise RuntimeError("Dropbox SDK not installed. Run: pip install dropbox")
        app_key = _secret_value("DROPBOX_APP_KEY")
        app_secret = _secret_value("DROPBOX_APP_SECRET")
        refresh_token = _secret_value("DROPBOX_REFRESH_TOKEN")
        if app_key and app_secret and refresh_token:
            return dbx_mod.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
        if dropbox_token:
            return dbx_mod.Dropbox(dropbox_token)
        raise RuntimeError("No Dropbox credentials: set DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN.")

    def list_dropbox_audio_files(self, dropbox_token: str, folder_path: str = "") -> List[Dict]:
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            result = dbx.files_list_folder(folder_path)
        except Exception as e:
            raise RuntimeError(f"Dropbox connection failed: {e}")
        return [{"name": e.name, "path": e.path_lower, "size": e.size}
                for e in result.entries
                if hasattr(e, "size") and os.path.splitext(e.name.lower())[1] in AUDIO_MIME_MAP]

    def download_bytes_from_dropbox(self, dropbox_token: str, file_path: str) -> bytes:
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            _, response = dbx.files_download(file_path)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {e}")

    def upload_bytes_to_dropbox(self, dropbox_token: str, data: bytes, dropbox_dest: str):
        try:
            import dropbox as dbx_mod
            client = self.get_dropbox_client(dropbox_token)
            client.files_upload(data, dropbox_dest, mode=dbx_mod.files.WriteMode.overwrite, mute=True)
        except Exception as e:
            raise RuntimeError(f"Dropbox upload failed: {e}")

    # ── Keywords ───────────────────────────────────────────────────────────────
    def _banned_keywords(self) -> List[str]:
        banned = list(rules.banned_list())
        folder = self.folders.get("02_VOICE_GUIDES")
        if folder and (folder / "Banned_Keywords.txt").exists():
            text = (folder / "Banned_Keywords.txt").read_text(encoding="utf-8")
            banned += [l.strip().lower() for l in text.splitlines() if l.strip()]
        return banned

    def process_keywords(self, keywords_raw, catalog: str, gemini_api_key: str) -> str:
        kw_list = gate.split_keywords(keywords_raw)
        if not kw_list:
            return ""
        client = genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))

        # (keyword, keep_whole). keep_whole marks a phrase the shortener never
        # got to — kept intact rather than chopped to a fragment like "End Of The".
        corrected = []
        self.keyword_warnings = []
        for kw in kw_list:
            if kw.count(" ") > 2:
                try:
                    response = client.models.generate_content(
                        model=self.gemini_model,
                        contents=self.prompts.keyword_shorten_prompt(kw),
                        config=types.GenerateContentConfig(
                            system_instruction=rules.system_instruction(catalog)),
                    )
                    new_kw = (response.text or "").strip()
                    corrected.append((new_kw, False) if new_kw else (kw, True))
                    if not new_kw:
                        self.keyword_warnings.append({"keyword": kw, "reason": "Shortener returned nothing"})
                except Exception as exc:
                    corrected.append((kw, True))
                    self.keyword_warnings.append({"keyword": kw, "reason": f"{type(exc).__name__}: {exc}"})
            else:
                corrected.append((kw, False))

        banned = self._banned_keywords()
        final = []
        for kw, keep_whole in corrected:
            if any(gate._find(b, kw) for b in banned):
                continue
            parts = kw.split()
            if len(parts) > 3 and not keep_whole:
                final.append(" ".join(parts[:3]).title())
            else:
                final.append(kw.title())

        if self.keyword_warnings:
            self._alert_keyword_warnings(catalog)
        return ", ".join(final[:20])

    def _alert_keyword_warnings(self, catalog: str):
        """Tell a human that a keyword went out unshortened. A failed alert never breaks a run."""
        try:
            from dropbox_pipeline import send_ntfy
            lines = "\n".join(f"- {w['keyword']}  ({w['reason']})" for w in self.keyword_warnings)
            send_ntfy("PFD - keywords not shortened",
                      f"Catalog: {catalog}\nKept whole and delivered as-is. Please review:\n{lines}")
        except Exception as exc:
            report("Keyword-review ntfy alert failed", exc)

    # ── Gemini plumbing ────────────────────────────────────────────────────────
    def _upload_to_gemini(self, file_bytes: bytes, ext: str, client):
        """Files API upload for large audio. The display name is generic: no title leaks."""
        uploaded = client.files.upload(
            file=io.BytesIO(file_bytes),
            config=types.UploadFileConfig(mime_type=AUDIO_MIME_MAP.get(ext.lower(), "audio/mpeg"),
                                          display_name="pfd-audio"),
        )
        while uploaded.state.name == "PROCESSING":
            time.sleep(2)
            uploaded = client.files.get(name=uploaded.name)
        if uploaded.state.name != "ACTIVE":
            raise RuntimeError(f"Gemini file upload failed — state '{uploaded.state.name}'")
        return uploaded

    def _audio_part(self, client, file_bytes: bytes, ext: str):
        if len(file_bytes) > gate.INLINE_LIMIT_BYTES:
            return self._upload_to_gemini(file_bytes, ext, client)
        mime = AUDIO_MIME_MAP.get(ext.lower(), "audio/mpeg")
        return types.Part(inline_data=types.Blob(mime_type=mime, data=file_bytes))

    def _gemini_json(self, client, contents, schema: Dict, catalog: str) -> str:
        config = types.GenerateContentConfig(
            system_instruction=rules.system_instruction(catalog),
            response_mime_type="application/json",
            response_schema=schema,
            temperature=gate.ANALYSIS_TEMPERATURE,
        )
        try:
            response = client.models.generate_content(model=self.gemini_model, contents=contents, config=config)
        except Exception as exc:
            if _is_quota_error(exc):
                from dropbox_pipeline import send_ntfy
                send_ntfy("⚠️ PFD — Gemini quota error", f"Pipeline paused: {exc}", priority="urgent")
            raise
        return response.text

    # ── The gated analysis ─────────────────────────────────────────────────────
    def analyze_track(self, file_bytes: bytes, ext: str, mix_type: str, catalog: str,
                      gemini_api_key: str) -> Dict:
        """
        Real duration → analysis → independent verification → (one re-run) → code checks.
        Returns {status, reasons, analysis_reasons, real_duration, analysis, verification, attempts}.
        Raises gate.SchemaViolation when the model's JSON does not match the schema.
        """
        real = gate.read_duration(file_bytes, ext)
        result = {"status": gate.BLOCKED, "reasons": [], "analysis_reasons": [], "real_duration": real,
                  "analysis": None, "verification": None, "attempts": 0}
        if real is None:
            result["reasons"] = result["analysis_reasons"] = ["no_duration"]
            return result

        client = genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))
        audio = self._audio_part(client, file_bytes, ext)
        mix = gate.mix_type_code(mix_type)

        disagree: List[str] = []
        for attempt in (1, 2):
            result["attempts"] = attempt
            analysis = gate.parse_analysis(self._gemini_json(
                client, [audio, self.prompts.analysis_prompt(mix, catalog)], gate.analysis_schema(), catalog))
            verification = gate.parse_verification(self._gemini_json(
                client, [audio, self.prompts.verification_prompt(gate.claims_for(analysis))],
                gate.verification_schema(), catalog))
            result["analysis"], result["verification"] = analysis, verification
            disagree = gate.disagreements(verification)
            if not disagree:
                break

        analysis["keywords_raw"] = list(analysis["keywords"])
        analysis["keywords"] = gate.split_keywords(self.process_keywords(analysis["keywords"], catalog, gemini_api_key))

        physical = [f"verification failed twice — {d}" for d in disagree]
        physical += [r for r in gate.analysis_reasons(analysis, real, catalog) if not r.startswith("keyword")]
        result["analysis_reasons"] = physical
        result["reasons"] = physical + gate.keyword_reasons(analysis["keywords"], catalog)
        result["status"] = gate.status_for(result["reasons"])
        return result

    # ── Track rows ─────────────────────────────────────────────────────────────
    def track_record(self, title: str, mix_type: str, result: Dict, catalog: str,
                     source_path: str = "", parent_track: str = "") -> Dict:
        """Join the title to an analysis result. This is the only place the two meet."""
        a = result.get("analysis") or {}
        real = result.get("real_duration")
        track = {
            "Title": title,
            "Mix Type": mix_type,
            "Parent Track": parent_track or base_title(title),
            "Source Path": source_path,
            "Duration": gate.format_time(real) if real else "",
            "Duration Seconds": real,
            "Ending Type": a.get("ending_type", ""),
            "Events": gate.format_events(a.get("events")),
            "Overall Consensus": a.get("job", ""),
            capture.context_label(catalog): a.get("trailer_or_campaign_voice", ""),
            "Editor Description": a.get("editor_voice", ""),
            "Supervisor Description": a.get("supervisor_voice", ""),
            "Keywords": ", ".join(a.get("keywords", [])),
            "Tip": a.get("tip", ""),
            "Gemini Description": a.get("description", ""),
            "Track Description": "",
            "analysis": a or None,
            "PFD_Analysis_Reasons": list(result.get("analysis_reasons") or result.get("reasons") or []),
            "PFD_Attempts": result.get("attempts", 0),
        }
        self.refresh_status(track, catalog)
        return track

    def blocked_record(self, title: str, mix_type: str, reason: str, catalog: str,
                       source_path: str = "", parent_track: str = "") -> Dict:
        """A row for a track whose analysis could not complete (schema violation, API error)."""
        return self.track_record(title, mix_type, {"analysis_reasons": [reason], "attempts": 0},
                                 catalog, source_path, parent_track)

    def refresh_status(self, track: Dict, catalog: str, lane: Optional[str] = None,
                       final: bool = False, parent: Optional[Dict] = None) -> Dict:
        """
        Recompute PFD_Status / PFD_Block_Reasons from the analysis reasons plus the
        current text. `final` (export) also requires a description to exist.
        """
        mix = (track.get("Mix Type") or "").lower()
        if mix == "alt" or mix.startswith("cutdown"):
            # Template text from folder names, not a listen: status follows the parent full mix.
            if parent is None:
                reasons = [f"parent track '{track.get('Parent Track', '')}' was not analysed"]
            elif parent.get("PFD_Status") != gate.PASSED:
                reasons = [f"parent track '{parent.get('Title', '')}' is BLOCKED"]
            else:
                reasons = []
        else:
            reasons = list(track.get("PFD_Analysis_Reasons") or [])
            if track.get("analysis"):
                reasons += gate.keyword_reasons(track.get("Keywords", ""), catalog, lane)
            elif not reasons:
                reasons.append("no analysis")
            desc = track.get("Track Description", "")
            if desc or final:
                reasons += gate.description_reasons(desc, catalog, base_title(track.get("Title", "")), lane)
        track["PFD_Block_Reasons"] = reasons
        track["PFD_Status"] = gate.status_for(reasons)
        return track

    def refresh_statuses(self, app_data: Dict, catalog: str, final: bool = False) -> int:
        """Refresh every track. Returns the BLOCKED count."""
        lane = app_data.get("lane") if rules.catalog_code(catalog) == "EPP" else None
        tracks = app_data.get("tracks", [])
        parents = {}
        for t in tracks:
            if (t.get("Mix Type") or "").lower() in ("full", "full_mix"):
                parents.setdefault(t.get("Parent Track") or base_title(t.get("Title", "")), t)
        for t in tracks:
            if (t.get("Mix Type") or "").lower() in ("full", "full_mix", "sparse", "sound_design", "sde", "unknown"):
                self.refresh_status(t, catalog, lane, final)
        for t in tracks:
            if t not in parents.values() and ((t.get("Mix Type") or "").lower() == "alt"
                                               or (t.get("Mix Type") or "").lower().startswith("cutdown")):
                self.refresh_status(t, catalog, lane, final, parents.get(t.get("Parent Track")))
        return sum(1 for t in tracks if t.get("PFD_Status") != gate.PASSED)

    # ── Claude ─────────────────────────────────────────────────────────────────
    def call_claude(self, system_instruction: str, prompt: str, claude_api_key: str,
                    max_tokens: int = 1024) -> str:
        """Raises ClaudeError. An error string is never returned as if it were copy."""
        if not claude_api_key:
            raise ClaudeError("No Claude API key configured.")
        client = anthropic.Anthropic(api_key=claude_api_key)
        try:
            message = client.messages.create(
                model=self.claude_model,
                max_tokens=max_tokens,
                system=system_instruction,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise ClaudeError(f"Claude call failed ({self.claude_model}): {type(exc).__name__}: {exc}") from exc
        text = "".join(b.text for b in message.content if getattr(b, "type", "text") == "text" and hasattr(b, "text"))
        if not text.strip():
            raise ClaudeError(f"Claude returned no text (stop_reason={getattr(message, 'stop_reason', '?')}).")
        return text.strip()

    # ── Track descriptions ─────────────────────────────────────────────────────
    def write_track_description(self, track: Dict, catalog: str, claude_api_key: str,
                                mode: Optional[str] = None, is_redo: bool = False,
                                user_guidance: str = "", lane: Optional[str] = None) -> str:
        mode = mode or rules.setting("track_writer")
        if mode not in WRITER_MODES:
            raise ValueError(f"track_writer '{mode}' is not one of {WRITER_MODES}")
        system = rules.system_instruction(catalog)
        if mode == "claude_synth":
            if not track.get("analysis"):
                raise ValueError(f"'{track.get('Title')}' has no analysis to write from.")
            return self.call_claude(system, self.prompts.track_synth_prompt(track, catalog, is_redo, user_guidance),
                                    claude_api_key)

        gemini_text = track.get("Gemini Description", "")
        if not gemini_text:
            raise ValueError(f"'{track.get('Title')}' has no Gemini description; re-run its analysis.")
        issues = gate.description_reasons(gemini_text, catalog, base_title(track.get("Title", "")), lane)
        if mode == "gemini" and not is_redo and not user_guidance:
            prompt = self.prompts.track_gate_prompt(gemini_text, issues)
        else:
            prompt = self.prompts.track_edit_prompt(track, catalog, gemini_text, issues, is_redo, user_guidance)
        return self.call_claude(system, prompt, claude_api_key)

    def writer_variants(self, track: Dict, catalog: str, claude_api_key: str,
                        lane: Optional[str] = None) -> Dict[str, str]:
        """All three writer modes for one track, for the blind writer test. Failures are shown."""
        out = {}
        for mode in WRITER_MODES:
            try:
                out[mode] = self.write_track_description(track, catalog, claude_api_key, mode=mode, lane=lane)
            except (ClaudeError, ValueError) as exc:
                report(f"Writer test: {mode} failed for '{track.get('Title')}'", exc)
                out[mode] = ""
        return out

    # ── EPP lane ───────────────────────────────────────────────────────────────
    def propose_lane(self, tracks: List[Dict], claude_api_key: str) -> str:
        summaries = [{k: (t.get("analysis") or {}).get(k) for k in ("job", "facts", "keywords", "ending_type")}
                     for t in tracks if t.get("analysis")]
        if not summaries:
            raise ValueError("No analysed tracks to propose a lane from.")
        text = self.call_claude(rules.system_instruction("EPP"),
                                self.prompts.lane_prompt(summaries, rules.lanes()),
                                claude_api_key, max_tokens=64)
        answer = text.strip().strip('."\'*').strip()
        match = next((n for n in rules.lane_names() if n.lower() == answer.lower()), None)
        if not match:
            raise ClaudeError(f"Lane proposal '{answer}' is not a lane in EPP_LANES.md.")
        return match

    def apply_lane(self, app_data: Dict, lane: str):
        if lane not in rules.lane_names():
            raise ValueError(f"'{lane}' is not a lane in EPP_LANES.md.")
        app_data["lane"] = lane
        for t in app_data.get("tracks", []):
            gate.apply_lane(t, lane)

    # ── Album ──────────────────────────────────────────────────────────────────
    def _recent_texts(self, catalog: str) -> List[str]:
        return [f"{e.get('album', '')}: {e.get('description', '')}".strip(": ")
                for e in recent_album_descriptions(catalog)]

    def generate_album_description(self, track_descriptions: List[str], catalog: str,
                                   claude_api_key: str) -> str:
        return self.call_claude(rules.system_instruction(catalog),
                                self.prompts.album_description_prompt(catalog, track_descriptions, self._recent_texts(catalog)),
                                claude_api_key)

    def generate_album_description_iteration(self, track_descriptions: List[str], catalog: str,
                                             iteration_history: List[Dict], user_guidance: str,
                                             claude_api_key: str) -> str:
        return self.call_claude(
            rules.system_instruction(catalog),
            self.prompts.album_description_iteration_prompt(
                catalog, track_descriptions, self._recent_texts(catalog), iteration_history, user_guidance),
            claude_api_key)

    @staticmethod
    def _parse_names(text: str) -> List[Dict]:
        m = re.search(r"\{.*\}", text or "", flags=re.DOTALL)
        try:
            data = json.loads(m.group(0)) if m else None
            names = data["names"]
            return [{"name": str(n["name"]).strip(), "rationale": str(n.get("rationale", "")).strip()}
                    for n in names]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ClaudeError(f"Album names were not valid JSON ({exc}): {str(text)[:200]!r}")

    def generate_album_names(self, album_description: str, catalog: str, claude_api_key: str,
                             track_descriptions: Optional[List[str]] = None) -> Dict[str, List[Dict]]:
        """Five candidates that pass the name rules, plus what was rejected and why."""
        taken = {e.get("album", "").strip().lower() for e in recent_album_descriptions(catalog)}
        accepted, rejected = [], []
        for round_no in range(2):
            need = 5 - len(accepted)
            avoid = [r["name"] for r in rejected] + [a["name"] for a in accepted]
            text = self.call_claude(
                rules.system_instruction(catalog),
                self.prompts.album_names_prompt(album_description, track_descriptions or [],
                                                count=need if round_no else 5, avoid=avoid or None),
                claude_api_key)
            for cand in self._parse_names(text):
                reasons = gate.album_name_reasons(cand["name"], catalog)
                if cand["name"].strip().lower() in taken:
                    reasons.append("already an album in the catalog")
                if reasons:
                    rejected.append({**cand, "reasons": reasons})
                elif len(accepted) < 5 and cand["name"].lower() not in {a["name"].lower() for a in accepted}:
                    accepted.append(cand)
            if len(accepted) >= 5:
                break
        return {"names": accepted, "rejected": rejected}

    def generate_cover_art_prompts(self, album_name: str, album_description: str, catalog: str,
                                   ref_urls: List[str], claude_api_key: str,
                                   track_descriptions: List[str] = None, keywords: str = None) -> str:
        return self.call_claude(
            rules.system_instruction(catalog),
            self.prompts.cover_art_prompt(catalog, album_name, album_description,
                                          track_descriptions or [], keywords or "", ref_urls),
            claude_api_key, max_tokens=2048)

    def generate_mailchimp_intro(self, album_name: str, album_description: str, catalog: str,
                                 claude_api_key: str, track_descriptions: List[str] = None) -> str:
        return self.call_claude(rules.system_instruction(catalog),
                                self.prompts.mailchimp_prompt(album_name, album_description, track_descriptions or []),
                                claude_api_key)

    def manual_refinement(self, content: str, content_type: str, catalog: str, claude_api_key: str) -> str:
        return self.call_claude(rules.system_instruction(catalog),
                                self.prompts.manual_refinement_prompt(content, content_type), claude_api_key)

    # ── Validator ──────────────────────────────────────────────────────────────
    def validate_data(self, data: Dict, catalog: str = "") -> Tuple[bool, List[str]]:
        """
        Export check. Refreshes every track's status with final=True, then lists
        everything that is not clean. BLOCKED tracks still export — with their
        status and reasons — so nothing is written as if it passed.
        """
        errors = []
        tracks = data.get("tracks", [])
        if not tracks:
            errors.append("No track data found to export.")
        self.refresh_statuses(data, catalog, final=True)
        for t in tracks:
            if t.get("PFD_Status") != gate.PASSED:
                errors.append(f"BLOCKED — {t.get('Title', '?')}: {'; '.join(t.get('PFD_Block_Reasons') or [])}")
        errors += [f"Album description: {r}" for r in gate.album_description_reasons(data.get("album_description", ""), catalog)]
        name = data.get("album_name_selected", "")
        errors += [f"Album name: {r}" for r in gate.album_name_reasons(name, catalog)]
        if rules.catalog_code(catalog) == "EPP" and not data.get("lane"):
            errors.append("EPP lane not confirmed (Tab 03).")
        return len(errors) == 0, errors

    def compile_final_package(self, data: Dict, catalog: str, album_code: str,
                              reference: Optional[List[str]] = None) -> Tuple[bytes, str]:
        return capture.build_zip(data, catalog, album_code, reference)
