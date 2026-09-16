"""
Publisher Final Delivery — engine (v4).

- Listen (Call A, Gemini + audio): the analyst brief, the measured duration,
  the audio and the mix type. Never the title, album, composer, filename,
  catalog or a previous track. The title is joined afterwards, here.
- Gate (gate.py): the analysis is checked against the decoded waveform
  (waveform.py) and against itself. One re-run; a second failure blocks.
- Write (Call B, Gemini, text only): the analysis without its scratchpad, the
  do_not_claim list, the catalog rules and few-shot examples.
- Claude: description gating/editing per `track_writer`, album description,
  names, lane proposal, MailChimp, cover-art prompts.
- Dropbox: folder access, album state and capture. Nothing writes to Google Drive.
"""
import datetime
import io
import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import anthropic
from google import genai
from google.genai import types

import capture
import gate
import rules
import waveform
from analysis_schema import Analysis, Presence, Writing, build_family_map, family_label, find_observation, simplify
from pfd_errors import report
from prompts import PromptEngine

log = logging.getLogger("pfd")

# ── Model pins ────────────────────────────────────────────────────────────────
# The app resolves the newest Opus / newest Pro at runtime (models.resolve).
# These pins are the fallback when that check fails. Setting GEMINI_AUDIO_MODEL
# or CLAUDE_WRITING_MODEL in Streamlit secrets (or env) locks the model instead.
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

# ── Generation configs (v4 build spec) ─────────────────────────────────────────
CALL_A_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=Analysis,
    temperature=0.0, top_p=1.0, top_k=1,
    candidate_count=1, max_output_tokens=6000,
)
CALL_B_CONFIG = types.GenerateContentConfig(
    response_mime_type="application/json",
    response_schema=Writing,
    temperature=0.7, top_p=0.95,
    candidate_count=1, max_output_tokens=8192,
)
# Gemini 3.x counts thinking tokens against max_output_tokens; at 2500 the JSON was
# cut off mid-string. A reply that is not valid JSON is written again once with this.
CALL_B_RETRY_MAX_OUTPUT_TOKENS = 16384

# Which Call A path ships (DECISIONS.md → "Call A schema path").
#   "schema": Gemini constrained decoding with response_schema=Analysis.
#   "prompt": JSON mode only, the JSON Schema pasted into the system instruction,
#             same Pydantic validation (a violation is G4).
# 2026-09-15: schema mode, after list caps above 7 moved out of the schema into
# Python. If Gemini returns any 400 INVALID_ARGUMENT, listen() re-issues the
# request in prompt mode and marks the track call_a_mode="prompt-fallback" —
# never silently (widened 2026-09-16: the message text is not dependable).
CALL_A_MODE = "schema"
CALL_A_PROMPT_CONFIG = CALL_A_CONFIG.model_copy(update={"response_schema": None})

# Wall-clock estimate per analysed file (listen, gate, write), for the Start
# screen. v3's live listen took ~28 s before its second listen; tune from runs.
SECONDS_PER_TRACK = 45

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

SKIPPED = "SKIPPED"
OVERRIDE = "OVERRIDE"
ANALYSED_MIXES = ("full", "full_mix", "sparse", "sound_design", "sde", "unknown")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def generated_text(track: Dict, field: str) -> str:
    """What the machine wrote for a field, before any human touched it."""
    return (track.get("PFD_Generated") or {}).get(field, "")


def record_revision(track: Dict, field: str, before: str, after: str, catalog: str,
                    album_code: str = "", action: str = "edit") -> Dict:
    """
    Keep both versions of a piece of copy: what the machine wrote and what the
    editor changed it to, with the catalog and the track it belongs to. Written
    into the track's PFD_Log, the same JSON the override log uses, so it travels
    in state.json. Nothing reads these yet — this is capture only, the first
    layer of style learning (DECISIONS.md → "Next RSI layer").
    """
    entry = {
        "action": action,
        "at": _now(),
        "field": field,
        "generated": generated_text(track, field),
        "from": before,
        "to": after,
        "catalog": rules.catalog_code(catalog) if catalog else "",
        "album_code": album_code,
        "track_id": track_key(track),
        "track": track.get("Title", ""),
        "mix_type": track.get("Mix Type", ""),
        "writer": rules.setting("track_writer"),
    }
    track.setdefault("PFD_Log", []).append(entry)
    return entry


def revisions(track: Dict) -> List[Dict]:
    return [e for e in track.get("PFD_Log") or [] if e.get("action") in ("edit", "manual")]


def override_reason(track: Dict) -> str:
    """The typed reason, whatever shape the record was written in."""
    o = track.get("PFD_Override")
    if isinstance(o, dict):
        return o.get("reason", "")
    return o or ""


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


def _is_invalid_argument(exc: Exception) -> bool:
    """
    Gemini's 400 INVALID_ARGUMENT on a Call A request. Any wording counts: the
    2026-09-14 schema rejections said only "Request contains an invalid argument.",
    so the message text cannot be relied on to spot a rejected schema.
    """
    msg = str(exc)
    return (getattr(exc, "code", None) == 400 or "400" in msg) and "INVALID_ARGUMENT" in msg


def recent_album_descriptions(catalog: str) -> List[Dict]:
    """The catalog's last ten album descriptions, seeded from master metadata."""
    if not RECENT_ALBUMS_PATH.exists():
        return []
    data = json.loads(RECENT_ALBUMS_PATH.read_text(encoding="utf-8"))
    return (data.get(rules.catalog_code(catalog)) or [])[:10]


def new_track_id() -> str:
    """A row's identity for the life of the album. Titles repeat; ids don't."""
    return "t" + uuid.uuid4().hex[:12]


def track_key(track: Dict) -> str:
    """
    The stable key a row is stored and looked up under. Rows written before
    v4 carry no id, so they fall back to their source path, then their title.
    """
    return track.get("track_id") or track.get("Source Path") or track.get("Title", "")


def is_alt_or_cutdown(track: Dict) -> bool:
    mix = (track.get("Mix Type") or "").lower()
    return mix == "alt" or mix.startswith("cutdown")


def remaining_uncertain(track: Dict) -> List[str]:
    """Uncertain families the editor has neither added nor dismissed."""
    g = track.get("PFD_Gate") or {}
    done = set(track.get("PFD_Added") or []) | set(track.get("PFD_Dismissed") or [])
    return [u for u in g.get("uncertain") or [] if u not in done]


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

    def download_bytes_from_dropbox(self, dropbox_token: str, file_path: str) -> bytes:
        try:
            dbx = self.get_dropbox_client(dropbox_token)
            _, response = dbx.files_download(file_path)
            return response.content
        except Exception as e:
            raise RuntimeError(f"Dropbox download failed: {e}")

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
    @staticmethod
    def _client(gemini_api_key: str):
        return genai.Client(api_key=gemini_api_key, http_options=types.HttpOptions(timeout=600000))

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

    def _generate(self, client, contents, base_config, system_instruction: str) -> str:
        config = base_config.model_copy(update={"system_instruction": system_instruction})
        try:
            response = client.models.generate_content(model=self.gemini_model, contents=contents, config=config)
        except Exception as exc:
            if _is_quota_error(exc):
                from dropbox_pipeline import send_ntfy
                send_ntfy("⚠️ PFD — Gemini quota error", f"Pipeline paused: {exc}", priority="urgent")
            raise
        return response.text

    # ── Call A + gate ──────────────────────────────────────────────────────────
    def _call_a(self, client, audio, user: str, duration: float, result: Dict) -> str:
        """
        One Call A request in the track's current mode. Any 400 INVALID_ARGUMENT
        re-issues the same request in prompt mode, and the record says so:
        result["call_a_mode"] = "prompt-fallback". Every other error raises.
        """
        if result["call_a_mode"] == "schema":
            try:
                return self._generate(client, [audio, user], CALL_A_CONFIG, self.prompts.call_a_system(duration))
            except Exception as exc:
                if not _is_invalid_argument(exc):
                    raise
                log.warning("Gemini rejected the Call A request (400 INVALID_ARGUMENT); "
                            "re-issuing in prompt mode: %s", str(exc)[:300])
                result["call_a_mode"] = "prompt-fallback"
                result["schema_error"] = str(exc)[:300]
        return self._generate(client, [audio, user], CALL_A_PROMPT_CONFIG,
                              self.prompts.call_a_system(duration, include_shape=True))

    def listen(self, file_bytes: bytes, ext: str, mix_type: str, gemini_api_key: str,
               correction: str = "", measured: Optional[Dict] = None) -> Dict:
        """
        Waveform → Call A → gate, at most two Call A per track.
        Returns {status, failures, measured, analysis, simple, uncertain, attempts, correction, call_a_mode}.
        API errors raise; a file that cannot be decoded is BLOCKED without calling the model.
        """
        mix = gate.mix_type_code(mix_type)
        result = {"status": gate.BLOCKED, "failures": [], "measured": None, "analysis": None,
                  "simple": None, "uncertain": [], "attempts": 0, "correction": (correction or "").strip(),
                  "call_a_mode": CALL_A_MODE}
        if measured is None:
            try:
                measured = waveform.measure_bytes(file_bytes, ext)
            except Exception as exc:
                report("Could not decode the audio file", exc, show=False)
                result["failures"] = [gate.failure("NO_AUDIO", error=f"{type(exc).__name__}: {exc}")]
                return result
        if not measured or measured.get("duration", 0) <= 0:
            result["failures"] = [gate.failure("NO_AUDIO", error="zero-length audio")]
            return result
        result["measured"] = measured
        duration = measured["duration"]

        client = self._client(gemini_api_key)
        audio = self._audio_part(client, file_bytes, ext)
        failures: List[Dict] = []
        for attempt in (1, 2):
            result["attempts"] = attempt
            user = self.prompts.call_a_user(mix, duration, hint=gate.retry_hint(failures),
                                            correction=result["correction"])
            text = self._call_a(client, audio, user, duration, result)
            try:
                analysis = gate.parse_analysis(text)
            except gate.SchemaViolation as exc:
                log.warning("Call A schema violation (attempt %s): %s", attempt, exc)
                failures = [gate.failure("G4", error=str(exc)[:400])]
                continue
            _, duplicates = build_family_map(analysis.instrumentation)
            if duplicates:
                log.warning("Call A listed a family twice; kept the higher confidence: %s", ", ".join(duplicates))
            result["duplicates"] = duplicates
            result["analysis"] = analysis.model_dump(mode="json")
            result["simple"] = simplify(analysis)
            result["uncertain"] = gate.uncertain_families(analysis)
            failures = gate.check_analysis(analysis, measured, mix)
            if not failures:
                break
        result["failures"] = failures
        result["status"] = gate.listen_status(failures, result["uncertain"])
        return result

    # ── Call B + writers ───────────────────────────────────────────────────────
    def write(self, track: Dict, catalog: str, gemini_api_key: str, claude_api_key: str,
              lane: Optional[str] = None, mode: Optional[str] = None, is_redo: bool = False,
              guidance: str = "", keywords_only: bool = False) -> Dict:
        """Call B, then the configured writer. Raises SchemaViolation / ClaudeError / API errors."""
        if not track.get("analysis"):
            raise ValueError(f"'{track.get('Title')}' has no analysis to write from.")
        client = self._client(gemini_api_key)
        prompt = self.prompts.call_b_prompt(track, catalog, is_redo, guidance)
        system = rules.system_instruction(catalog)
        text = self._generate(client, prompt, CALL_B_CONFIG, system)
        try:
            json.loads(text or "")
        except json.JSONDecodeError as exc:
            log.warning("Call B reply was not valid JSON (%s; likely cut off at %d tokens); writing again with %d.",
                        exc, CALL_B_CONFIG.max_output_tokens, CALL_B_RETRY_MAX_OUTPUT_TOKENS)
            text = self._generate(client, prompt, CALL_B_CONFIG.model_copy(
                update={"max_output_tokens": CALL_B_RETRY_MAX_OUTPUT_TOKENS}), system)
        writing = gate.parse_writing(text)
        track["Keywords"] = self.process_keywords(writing.keywords, catalog, gemini_api_key)
        track["PFD_Keyword_Warnings"] = list(self.keyword_warnings)
        if lane:
            gate.apply_lane(track, lane)
        if keywords_only:
            return track
        track[capture.context_label(catalog)] = writing.trailer_or_campaign_voice
        track["Editor Description"] = writing.editor_voice
        track["Supervisor Description"] = writing.supervisor_voice
        track["Tip"] = writing.tip
        track["Gemini Description"] = writing.description
        track["Track Description"] = self.finish_description(track, catalog, claude_api_key, lane, mode)
        # The baseline a later human edit is measured against.
        track["PFD_Generated"] = {"Track Description": track["Track Description"],
                                  "Keywords": track.get("Keywords", ""), "at": _now()}
        track.pop("PFD_Write_Error", None)
        if lane:
            gate.apply_lane(track, lane)
        return track

    def finish_description(self, track: Dict, catalog: str, claude_api_key: str,
                           lane: Optional[str] = None, mode: Optional[str] = None,
                           is_redo: bool = False, guidance: str = "") -> str:
        mode = mode or rules.setting("track_writer")
        if mode not in WRITER_MODES:
            raise ValueError(f"track_writer '{mode}' is not one of {WRITER_MODES}")
        system = rules.system_instruction(catalog)
        if mode == "claude_synth":
            return self.call_claude(system, self.prompts.track_synth_prompt(track, catalog, is_redo, guidance),
                                    claude_api_key)
        gemini_text = track.get("Gemini Description", "")
        issues = [gate.reason_text(r) for r in
                  gate.description_reasons(gemini_text, catalog, base_title(track.get("Title", "")), lane)]
        if mode == "claude_edit":
            return self.call_claude(system, self.prompts.track_edit_prompt(track, catalog, gemini_text, issues,
                                                                           is_redo, guidance), claude_api_key)
        try:
            return self.call_claude(system, self.prompts.track_gate_prompt(track, gemini_text, issues),
                                    claude_api_key)
        except ClaudeError as exc:
            report(f"Claude could not gate the description for '{track.get('Title')}' — Gemini's text is kept", exc)
            notes = track.setdefault("PFD_Notes", [])
            if "Not checked by Claude." not in notes:
                notes.append("Not checked by Claude.")
            return gemini_text

    def writer_variants(self, track: Dict, catalog: str, claude_api_key: str,
                        lane: Optional[str] = None) -> Dict[str, str]:
        """All three writer modes for one track, for "Compare writing styles". Failures are shown."""
        out = {}
        for mode in WRITER_MODES:
            try:
                out[mode] = self.finish_description(track, catalog, claude_api_key, lane, mode=mode)
            except (ClaudeError, ValueError) as exc:
                report(f"Compare writing styles: {mode} failed for '{track.get('Title')}'", exc)
                out[mode] = ""
        return out

    # ── One track, end to end ──────────────────────────────────────────────────
    def process_track(self, title: str, mix_type: str, data: bytes, ext: str, catalog: str,
                      gemini_api_key: str, claude_api_key: str, lane: Optional[str] = None,
                      source_path: str = "", parent_track: str = "", correction: str = "",
                      track_id: str = "") -> Dict:
        """Listen, gate, write. Quota errors raise so the run can stop; other write failures land on the row."""
        result = self.listen(data, ext, mix_type, gemini_api_key, correction=correction)
        track = self.track_record(title, mix_type, result, catalog, source_path, parent_track, track_id)
        if track.get("analysis") and (track["PFD_Gate"]["status"] in gate.READY):
            self.try_write(track, catalog, gemini_api_key, claude_api_key, lane)
        self.refresh_status(track, catalog, lane)
        return track

    def try_write(self, track: Dict, catalog: str, gemini_api_key: str, claude_api_key: str,
                  lane: Optional[str] = None, **kwargs) -> bool:
        try:
            self.write(track, catalog, gemini_api_key, claude_api_key, lane, **kwargs)
            return True
        except Exception as exc:
            if _is_quota_error(exc):
                raise
            report(f"Writing failed — {track.get('Title')}", exc)
            track["PFD_Write_Error"] = f"{type(exc).__name__}: {exc}"[:300]
            return False

    # ── Track rows ─────────────────────────────────────────────────────────────
    def track_record(self, title: str, mix_type: str, result: Dict, catalog: str,
                     source_path: str = "", parent_track: str = "", track_id: str = "") -> Dict:
        """
        Join the title to a listen result. This is the only place the two meet.
        `track_id` carries a row's identity through a re-run, so a fresh result
        replaces the right row instead of one that happens to share a title.
        """
        a = result.get("analysis") or {}
        simple = result.get("simple") or {}
        measured = result.get("measured") or {}
        duration = measured.get("duration")
        gate_state = {
            "status": result.get("status", gate.BLOCKED),
            "failures": list(result.get("failures") or []),
            "attempts": result.get("attempts", 0),
            "uncertain": list(result.get("uncertain") or []),
            "override_note": "",
        }
        if result.get("correction") and a:
            gate_state["override_note"] = f"Corrected by editor: {result['correction']}"
            gate_state["status"] = gate.PASSED
        track = {
            "track_id": track_id or new_track_id(),
            "Title": title,
            "Mix Type": mix_type,
            "Parent Track": parent_track or base_title(title),
            "Source Path": source_path,
            "Duration": gate.format_time(duration) if duration else "",
            "Duration Seconds": duration,
            "Ending Type": gate.ENDING_LABELS.get(simple.get("ending_type"), ""),
            "Sections": gate.format_sections(a.get("sections")),
            "Overall Consensus": a.get("the_job", ""),
            capture.context_label(catalog): "",
            "Editor Description": "",
            "Supervisor Description": "",
            "Keywords": "",
            "Tip": "",
            "Gemini Description": "",
            "Track Description": "",
            "analysis": a or None,
            "simple": simple or None,
            "measured": {k: v for k, v in measured.items() if k != "per_sec_db"} or None,
            "call_a_mode": result.get("call_a_mode", ""),
            "PFD_Gate": gate_state,
            "PFD_Notes": [],
            "PFD_Added": [],
            "PFD_Dismissed": [],
        }
        self.refresh_status(track, catalog)
        return track

    def blocked_record(self, title: str, mix_type: str, fail: Dict, catalog: str,
                       source_path: str = "", parent_track: str = "", track_id: str = "") -> Dict:
        """A row for a track whose listen could not complete (decode failure, API error)."""
        return self.track_record(title, mix_type, {"failures": [fail], "status": gate.BLOCKED},
                                 catalog, source_path, parent_track, track_id)

    def refresh_status(self, track: Dict, catalog: str, lane: Optional[str] = None,
                       final: bool = False, parent: Optional[Dict] = None) -> Dict:
        """
        PFD_Status / PFD_Block_Reasons (plain sentences) from the listen and the
        current text. `final` (export) also requires a description and keywords.
        PFD_Reason_Kind is "listen" when the analysis itself is blocked, "text" otherwise.
        """
        kind = ""
        if track.get("PFD_Skipped"):
            reasons, status = [], SKIPPED
        elif is_alt_or_cutdown(track):
            # Template text from folder names, not a listen: status follows the parent full mix.
            if parent is None:
                reasons = [gate.failure("PARENT", title=track.get("Parent Track", ""), status="not analysed")]
            elif parent.get("PFD_Status") not in gate.READY:
                reasons = [gate.failure("PARENT", title=parent.get("Title", ""), status="blocked")]
            else:
                reasons = []
            status = gate.BLOCKED if reasons else gate.PASSED
        else:
            g = track.get("PFD_Gate") or {}
            manual = bool(track.get("PFD_Manual"))
            overridden = bool(track.get("PFD_Override"))
            reasons = []
            if overridden:
                # An editor listened and accepted this track. Nothing re-blocks it;
                # the reasons it overrode stay on the row and in the export.
                kind = ""
                reasons = []
            elif not manual and g.get("status") == gate.BLOCKED:
                kind = "listen"
                reasons = list(g.get("failures") or []) or [gate.failure("NO_ANALYSIS")]
            else:
                kind = "text"
                if track.get("PFD_Write_Error") and not manual:
                    reasons.append(gate.failure("WRITE", error=track["PFD_Write_Error"]))
                if track.get("analysis") or manual:
                    if track.get("Keywords") or final:
                        reasons += gate.keyword_reasons(track.get("Keywords", ""), catalog, lane)
                    desc = track.get("Track Description", "")
                    if desc or final:
                        reasons += gate.description_reasons(desc, catalog, base_title(track.get("Title", "")), lane)
                else:
                    kind = "listen"
                    reasons.append(gate.failure("NO_ANALYSIS"))
            if reasons:
                status = gate.BLOCKED
            elif overridden:
                status = OVERRIDE          # passed by a human, and the row says so
            elif not manual and not g.get("override_note") and remaining_uncertain(track):
                status = gate.PASSED_WITH_UNCERTAINTY
            else:
                status = gate.PASSED
        track["PFD_Block_Reasons"] = reasons
        track["PFD_Status"] = status
        track["PFD_Reason_Kind"] = kind if status == gate.BLOCKED else ""
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
            if not is_alt_or_cutdown(t):
                self.refresh_status(t, catalog, lane, final)
        for t in tracks:
            if is_alt_or_cutdown(t):
                self.refresh_status(t, catalog, lane, final, parents.get(t.get("Parent Track")))
        return sum(1 for t in tracks if t.get("PFD_Status") == gate.BLOCKED)

    @staticmethod
    def status_counts(tracks: List[Dict]) -> Dict[str, int]:
        c = {"ready": 0, "uncertain": 0, "blocked": 0, "skipped": 0, "override": 0}
        for t in tracks:
            s = t.get("PFD_Status")
            c["ready" if s == gate.PASSED else "uncertain" if s == gate.PASSED_WITH_UNCERTAINTY
              else "skipped" if s == SKIPPED else "override" if s == OVERRIDE else "blocked"] += 1
        return c

    # ── Fix actions (Review screen) ────────────────────────────────────────────
    def add_family(self, track: Dict, family_path: str, catalog: str, gemini_api_key: str,
                   claude_api_key: str, lane: Optional[str] = None) -> bool:
        """The editor confirms an uncertain family is there. Call B only — no re-listen."""
        obs = find_observation(track.get("analysis"), family_path)
        if obs is None:
            raise ValueError(f"No family '{family_path}' in the analysis.")
        obs.update({"presence": Presence.present.value, "prominence": obs.get("prominence") or "supporting",
                    "confidence": 1.0, "note": "Confirmed by an editor who listened."})
        simple = track.get("simple") or {}
        simple["do_not_claim"] = [p for p in simple.get("do_not_claim") or [] if p != family_path]
        track.setdefault("PFD_Added", []).append(family_path)
        ok = self.try_write(track, catalog, gemini_api_key, claude_api_key, lane)
        self.refresh_status(track, catalog, lane)
        return ok

    def dismiss_family(self, track: Dict, family_path: str, catalog: str, lane: Optional[str] = None):
        track.setdefault("PFD_Dismissed", []).append(family_path)
        self.refresh_status(track, catalog, lane)

    def override_track(self, track: Dict, catalog: str, gemini_api_key: str, claude_api_key: str,
                       note: str, lane: Optional[str] = None) -> bool:
        """
        The editor listened and accepts the analysis. The reason is required, it is
        stamped with the time, and the reasons it overrode are kept alongside it —
        an override never deletes the original block. The description is written
        afterwards if the block had stopped it being written at all.
        """
        reason = (note or "").strip()
        if not reason:
            raise ValueError("An override needs a reason.")
        overrode = [gate.summary(f) for f in gate.normalize(track.get("PFD_Block_Reasons"))]
        track["PFD_Override"] = {
            "reason": reason,
            "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
            "overrode": overrode,
        }
        track.setdefault("PFD_Log", []).append(
            {"action": "override", "at": track["PFD_Override"]["at"], "reason": reason, "overrode": overrode})
        wrote = True
        if track.get("analysis") and not track.get("Track Description"):
            wrote = self.try_write(track, catalog, gemini_api_key, claude_api_key, lane)
        self.refresh_status(track, catalog, lane)
        return wrote

    def manual_description(self, track: Dict, text: str, catalog: str, gemini_api_key: str,
                           lane: Optional[str] = None, keywords: str = "", album_code: str = "") -> List[Dict]:
        """
        "I'll write it". Returns the rule problems in the text; nothing is saved
        while there are any. Keywords come from Call B when there is an analysis;
        otherwise the editor types them. Both versions are kept.
        """
        problems = gate.description_reasons(text, catalog, base_title(track.get("Title", "")), lane)
        if problems:
            return problems
        record_revision(track, "Track Description", track.get("Track Description", ""), text.strip(),
                        catalog, album_code, action="manual")
        track["Track Description"] = text.strip()
        track["PFD_Manual"] = True
        track.pop("PFD_Write_Error", None)
        if track.get("analysis"):
            self.write(track, catalog, gemini_api_key, "", lane, keywords_only=True)
        else:
            track["Keywords"] = keywords
        if lane:
            gate.apply_lane(track, lane)
        self.refresh_status(track, catalog, lane)
        return []

    @staticmethod
    def skip(track: Dict, skipped: bool = True):
        track["PFD_Skipped"] = skipped

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

    # ── EPP lane ───────────────────────────────────────────────────────────────
    def propose_lane(self, tracks: List[Dict], claude_api_key: str) -> str:
        summaries = []
        for t in tracks:
            a, s = t.get("analysis"), t.get("simple") or {}
            if not a:
                continue
            summaries.append({"job": a.get("the_job"), "genre_tags": a.get("genre_tags"),
                              "energy_arc": s.get("energy_arc"), "tempo_band": s.get("tempo_band"),
                              "lead_sources": [family_label(p) for p in s.get("lead_sources") or []],
                              "keywords": gate.split_keywords(t.get("Keywords", ""))})
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
                                   claude_api_key: str, previous: str = "", guidance: str = "") -> str:
        return self.call_claude(rules.system_instruction(catalog),
                                self.prompts.album_description_prompt(catalog, track_descriptions,
                                                                      self._recent_texts(catalog), previous, guidance),
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

    # ── Validator ──────────────────────────────────────────────────────────────
    def validate_data(self, data: Dict, catalog: str = "") -> Tuple[bool, List[str]]:
        """
        Export check. Refreshes every track with final=True and lists what is not
        clean. The Export button stays grey while any track is BLOCKED; album-level
        issues are listed but do not stop the export.
        """
        errors: List[str] = []
        tracks = [t for t in data.get("tracks", []) if not t.get("PFD_Skipped")]
        if not tracks:
            errors.append("No tracks to export.")
        self.refresh_statuses(data, catalog, final=True)
        for t in tracks:
            if t.get("PFD_Status") == gate.BLOCKED:
                errors.append(f"{t.get('Title', '?')} — "
                              + " · ".join(gate.summary(f) for f in gate.normalize(t.get("PFD_Block_Reasons"))))
        errors += [f"Album description: {r}" for r in gate.album_description_reasons(data.get("album_description", ""), catalog)]
        name = data.get("album_name_selected", "")
        errors += [f"Album name: {r}" for r in gate.album_name_reasons(name, catalog)]
        if rules.catalog_code(catalog) == "EPP" and not data.get("lane"):
            errors.append("EPP lane not confirmed.")
        return len(errors) == 0, errors
