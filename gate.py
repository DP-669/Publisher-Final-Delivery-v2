"""
The hallucination gate.

Everything here is plain code, independent of any model: it decides whether an
analysis can be proven real and whether finished text obeys PFD_RULES.md.
engine.py calls the models; this module judges what came back.

A track is PASSED or BLOCKED. BLOCKED always carries reasons, and those reasons
travel into the export. Nothing in this module converts BLOCKED into a result.
"""
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

import rules

PASSED = "PASSED"
BLOCKED = "BLOCKED"

# Gemini sampling temperature for the analysis and verification calls. Low, so
# two listens to the same file agree on facts rather than on flourishes.
# Google's Gemini 3 guide recommends leaving temperature at 1.0 (lower values
# can loop on long reasoning). The build spec asked to start at 0.3; if real
# runs show looping or truncated JSON, raise this to 1.0. See DECISIONS.md.
ANALYSIS_TEMPERATURE = 0.3

DURATION_TOLERANCE = 0.08          # abs(claimed - real) <= 8% of real
KEYWORD_MIN, KEYWORD_MAX = 12, 18
INLINE_LIMIT_BYTES = 15 * 1024 * 1024   # larger files go through the Files API

MIX_TYPES = ("FULL", "SPARSE", "SDE")
ENDING_TYPES = ["Hard Cut", "Button", "Ring-out"]
TEMPO_BANDS = ["Slow", "Mid", "Fast", "Rubato"]
# What the second listen audits. Only facts two listens reliably agree on:
# drums (timpani vs none) and tempo band flipped between listens of the same
# file, and duration is already checked against the file in code. See GATE_FIX.md.
VERIFIED_CLAIMS = ("vocals", "choir", "ending_type")


class SchemaViolation(RuntimeError):
    """The model's JSON does not match the analysis schema. A hard error, never a guess."""


# ── Mix type ───────────────────────────────────────────────────────────────────

def mix_type_code(mix_type: str) -> str:
    """Map the app's mix labels ('full', 'sparse', 'sound_design', 'Sound Design') to FULL/SPARSE/SDE."""
    m = (mix_type or "").strip().lower().replace(" ", "_")
    if m in ("sparse", "sparse_mix", "sparce"):
        return "SPARSE"
    if m in ("sde", "sound_design", "sound_design_element"):
        return "SDE"
    return "FULL"


# ── Real duration ──────────────────────────────────────────────────────────────

def read_duration(data: bytes, ext: str) -> Optional[float]:
    """
    True duration in seconds from the file itself, before any API call.
    mutagen reads the header; ffprobe is the fallback. None means the file's
    length cannot be proven, and the caller must BLOCK with `no_duration`.
    """
    ext = ext if ext.startswith(".") else f".{ext}"
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        seconds = _mutagen_duration(path)
        if seconds is None:
            seconds = _ffprobe_duration(path)
        return seconds
    finally:
        os.remove(path)


def _mutagen_duration(path: str) -> Optional[float]:
    try:
        import mutagen
        audio = mutagen.File(path)
    except Exception as exc:  # corrupt header: fall through to ffprobe
        print(f"[PFD gate] mutagen could not read {os.path.basename(path)}: {exc}")
        return None
    length = getattr(getattr(audio, "info", None), "length", None)
    return float(length) if length and length > 0 else None


def _ffprobe_duration(path: str) -> Optional[float]:
    if not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        value = float(out)
        return value if value > 0 else None
    except (ValueError, subprocess.SubprocessError) as exc:
        print(f"[PFD gate] ffprobe could not read {os.path.basename(path)}: {exc}")
        return None


# ── Schemas (mirror the TUNABLE "Analysis schema" block) ───────────────────────

def analysis_schema() -> Dict:
    """
    Gemini response_schema. Keys match PFD_RULES.md's Analysis schema block
    (test_rules checks they stay in sync), plus `description`: the track
    description Gemini writes in the same listen, used by the `gemini` and
    `claude_edit` writer modes.
    """
    s = {"type": "STRING"}
    return {
        "type": "OBJECT",
        "properties": {
            "mix_type": {"type": "STRING", "enum": list(MIX_TYPES)},
            "duration_seconds": {"type": "NUMBER"},
            "ending_type": {"type": "STRING", "enum": ENDING_TYPES},
            "events": {
                "type": "ARRAY", "min_items": 3, "max_items": 6,
                "items": {
                    "type": "OBJECT",
                    "properties": {"t": {"type": "NUMBER"}, "what": s},
                    "required": ["t", "what"],
                },
            },
            "facts": {
                "type": "OBJECT",
                "properties": {
                    "drums": {"type": "BOOLEAN"},
                    "vocals": {"type": "BOOLEAN"},
                    "choir": {"type": "BOOLEAN"},
                    "tempo_band": {"type": "STRING", "enum": TEMPO_BANDS},
                    "energy_arc": s,
                },
                "required": ["drums", "vocals", "choir", "tempo_band", "energy_arc"],
            },
            "job": s,
            "narrative_map": s,
            "trailer_or_campaign_voice": s,
            "editor_voice": s,
            "supervisor_voice": s,
            "keywords": {"type": "ARRAY", "min_items": KEYWORD_MIN, "max_items": KEYWORD_MAX, "items": s},
            "tip": s,
            "description": s,
        },
        "required": ["mix_type", "duration_seconds", "ending_type", "events", "facts", "job",
                     "narrative_map", "trailer_or_campaign_voice", "editor_voice",
                     "supervisor_voice", "keywords", "tip", "description"],
        "property_ordering": ["mix_type", "duration_seconds", "ending_type", "events", "facts",
                              "job", "narrative_map", "trailer_or_campaign_voice", "editor_voice",
                              "supervisor_voice", "keywords", "tip", "description"],
    }


def verification_schema() -> Dict:
    verdict = {"type": "STRING", "enum": ["TRUE", "FALSE"]}
    return {
        "type": "OBJECT",
        "properties": {c: verdict for c in VERIFIED_CLAIMS},
        "required": list(VERIFIED_CLAIMS),
    }


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _load_json(text: str, what: str) -> Dict:
    try:
        obj = json.loads(text or "")
    except (json.JSONDecodeError, TypeError) as exc:
        raise SchemaViolation(f"{what}: response is not JSON ({exc}). First 200 chars: {str(text)[:200]!r}")
    if not isinstance(obj, dict):
        raise SchemaViolation(f"{what}: response is not a JSON object.")
    return obj


def parse_analysis(text: str) -> Dict:
    """Parse and validate an analysis response. Raises SchemaViolation on any mismatch."""
    obj = _load_json(text, "analysis")
    problems = []
    schema = analysis_schema()
    for key in schema["required"]:
        if key not in obj:
            problems.append(f"missing '{key}'")
    if problems:
        raise SchemaViolation("analysis: " + "; ".join(problems))

    if obj["mix_type"] not in MIX_TYPES:
        problems.append(f"mix_type '{obj['mix_type']}' not in {MIX_TYPES}")
    if not _is_num(obj["duration_seconds"]):
        problems.append("duration_seconds is not a number")
    if obj["ending_type"] not in ENDING_TYPES:
        problems.append(f"ending_type '{obj['ending_type']}' not in {ENDING_TYPES}")
    events = obj["events"]
    if not isinstance(events, list) or not 3 <= len(events) <= 6:
        problems.append("events must be a list of 3–6 entries")
    else:
        for i, e in enumerate(events):
            if not isinstance(e, dict) or not _is_num(e.get("t")) or not isinstance(e.get("what"), str):
                problems.append(f"events[{i}] must be {{t: number, what: string}}")
    facts = obj["facts"]
    if not isinstance(facts, dict):
        problems.append("facts is not an object")
    else:
        for k in ("drums", "vocals", "choir"):
            if not isinstance(facts.get(k), bool):
                problems.append(f"facts.{k} is not a boolean")
        if facts.get("tempo_band") not in TEMPO_BANDS:
            problems.append(f"facts.tempo_band '{facts.get('tempo_band')}' not in {TEMPO_BANDS}")
        if not isinstance(facts.get("energy_arc"), str):
            problems.append("facts.energy_arc is not a string")
    if not isinstance(obj["keywords"], list) or not all(isinstance(k, str) for k in obj["keywords"]):
        problems.append("keywords is not a list of strings")
    for k in ("job", "narrative_map", "trailer_or_campaign_voice", "editor_voice",
              "supervisor_voice", "tip", "description"):
        if not isinstance(obj[k], str):
            problems.append(f"{k} is not a string")
    if problems:
        raise SchemaViolation("analysis: " + "; ".join(problems))
    return obj


def parse_verification(text: str) -> Dict:
    obj = _load_json(text, "verification")
    problems = [f"missing '{k}'" for k in VERIFIED_CLAIMS if k not in obj]
    problems += [f"{k} must be TRUE or FALSE" for k in VERIFIED_CLAIMS
                 if k in obj and obj[k] not in ("TRUE", "FALSE")]
    if problems:
        raise SchemaViolation("verification: " + "; ".join(problems))
    return obj


# ── Verification ───────────────────────────────────────────────────────────────

def claims_for(analysis: Dict) -> Dict[str, str]:
    """The hard facts the second listen audits, as plain statements. No title, no prose."""
    f = analysis["facts"]
    yes = lambda b: "present" if b else "absent"
    return {
        "vocals": f"Vocals are {yes(f['vocals'])}.",
        "choir": f"Choir is {yes(f['choir'])}.",
        "ending_type": f"The ending type is {analysis['ending_type']}.",
    }


def within_tolerance(claimed: float, real: float) -> bool:
    return abs(claimed - real) <= DURATION_TOLERANCE * real


def disagreements(verification: Dict) -> List[str]:
    return [f"second listen disagrees: {c}" for c in VERIFIED_CLAIMS if verification.get(c) != "TRUE"]


# ── Physical checks on an analysis ─────────────────────────────────────────────

def analysis_reasons(analysis: Dict, real_duration: float, catalog: str) -> List[str]:
    reasons = []
    claimed = float(analysis["duration_seconds"])
    if not within_tolerance(claimed, real_duration):
        reasons.append(f"duration mismatch: analysis says {claimed:.1f}s, file is {real_duration:.1f}s (>8%)")
    for e in analysis["events"]:
        if float(e["t"]) > real_duration:
            reasons.append(f"event at {float(e['t']):.1f}s is past the end of the file ({real_duration:.1f}s)")
    reasons += keyword_reasons(analysis["keywords"], catalog)
    return reasons


# ── Text checks ────────────────────────────────────────────────────────────────

def _find(phrase: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){re.escape(phrase)}(?![A-Za-z])", text, flags=re.IGNORECASE) is not None


def banned_found(text: str) -> List[str]:
    return [w for w in rules.banned_list() if _find(w, text or "")]


def forbidden_found(text: str, catalog: str, lead: bool = True) -> List[str]:
    """
    Forbidden placement words for the catalog. Words with a qualifier
    (SSC: "trailer (as a lead placement)") only count when `lead` is True,
    i.e. in a first sentence, a Fits line or a first keyword.
    """
    out = []
    for item in rules.forbidden_placement_words(catalog):
        if item["qualifier"] and not lead:
            continue
        if _find(item["word"], text or ""):
            out.append(item["word"])
    return out


def split_keywords(keywords) -> List[str]:
    if isinstance(keywords, list):
        items = keywords
    else:
        items = re.split(r"[,;]", keywords or "")
    return [k.strip() for k in items if k and k.strip()]


def keyword_reasons(keywords, catalog: str, lane: Optional[str] = None) -> List[str]:
    kws = split_keywords(keywords)
    reasons = []
    if not KEYWORD_MIN <= len(kws) <= KEYWORD_MAX:
        reasons.append(f"keyword count {len(kws)} (must be {KEYWORD_MIN}–{KEYWORD_MAX})")
    for i, kw in enumerate(kws):
        if len(kw.split()) > 3:
            reasons.append(f"keyword '{kw}' is longer than 3 words")
        if banned_found(kw):
            reasons.append(f"keyword '{kw}' contains a banned word")
        bad = forbidden_found(kw, catalog, lead=(i == 0))
        if bad:
            reasons.append(f"keyword '{kw}' uses a forbidden placement word ({', '.join(bad)})")
        if _find("cinematic", kw):
            reasons.append(f"keyword '{kw}': 'cinematic' is never a keyword")
    if lane and (not kws or kws[0].lower() != lane.lower()):
        reasons.append(f"first keyword must be the lane '{lane}'")
    return reasons


FITS_RE = re.compile(r"Fits:\s*([^\n]+?)\s*\.?\s*$", flags=re.IGNORECASE)


def split_fits(description: str):
    """(body, [tags]) — tags is None when the description has no trailing Fits line."""
    text = (description or "").strip()
    m = FITS_RE.search(text)
    if not m:
        return text, None
    tags = [t.strip().rstrip(".").strip() for t in m.group(1).split(",") if t.strip()]
    return text[:m.start()].strip(), tags


def join_fits(body: str, tags: List[str]) -> str:
    return f"{body.strip()} Fits: {', '.join(tags)}".strip()


def sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def _fits_key(tag: str) -> str:
    """
    Comparison key for a Fits tag: lowercase, single spaces, plural folded, so
    'documentaries' matches 'Documentary'. Comparison only; the description
    keeps the tag exactly as written.
    """
    t = " ".join((tag or "").lower().split())
    if t.endswith("ies") and len(t) > 4:
        return t[:-3] + "y"
    if t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def fits_reasons(tags: Optional[List[str]], catalog: str, lane: Optional[str] = None) -> List[str]:
    if tags is None:
        return ["description does not end with a 'Fits:' line"]
    reasons = []
    if not 2 <= len(tags) <= 3:
        reasons.append(f"Fits line has {len(tags)} tags (must be 2–3)")
    legal = {_fits_key(t) for t in rules.fits_list(catalog)}
    is_epp = rules.catalog_code(catalog) == "EPP"
    lane_names = {n.lower() for n in rules.lane_names()}
    for i, tag in enumerate(tags):
        if is_epp and i == 0 and (tag.lower() == (lane or "").lower() or (not lane and tag.lower() in lane_names)):
            continue
        if _fits_key(tag) not in legal:
            reasons.append(f"Fits tag '{tag}' is not in the {rules.catalog_code(catalog)} placement list")
    if is_epp and lane and (not tags or tags[0].lower() != lane.lower()):
        reasons.append(f"first Fits tag must be the lane '{lane}'")
    return reasons


def description_reasons(description: str, catalog: str, title: str = "",
                        lane: Optional[str] = None) -> List[str]:
    desc = (description or "").strip()
    if not desc:
        return ["track description is empty"]
    body, tags = split_fits(desc)
    reasons = fits_reasons(tags, catalog, lane)
    sents = sentences(body)
    if not 2 <= len(sents) <= 3:
        reasons.append(f"description has {len(sents)} sentences before Fits (must be 2–3)")
    bad = banned_found(desc)
    if bad:
        reasons.append(f"description uses banned words: {', '.join(bad)}")
    lead_text = (sents[0] if sents else "") + " " + ", ".join(tags or [])
    rest = " ".join(sents[1:])
    bad = sorted(set(forbidden_found(lead_text, catalog, lead=True) + forbidden_found(rest, catalog, lead=False)))
    if bad:
        reasons.append(f"description uses forbidden placement words for {rules.catalog_code(catalog)}: {', '.join(bad)}")
    if sents and _find("cinematic", sents[0]):
        reasons.append("'cinematic' in the first sentence")
    if title and len(title.strip()) > 2 and _find(title.strip(), desc):
        reasons.append("description contains the track title")
    if _find("this track", desc):
        reasons.append("description says 'this track'")
    return reasons


def album_description_reasons(text: str, catalog: str) -> List[str]:
    t = (text or "").strip()
    if not t:
        return ["album description is empty"]
    reasons = []
    words = len(t.split())
    if not 6 <= words <= 20:
        reasons.append(f"album description is {words} words (must be 6–20)")
    if len(sentences(t)) != 1:
        reasons.append("album description must be one sentence")
    bad = banned_found(t)
    if bad:
        reasons.append(f"album description uses banned words: {', '.join(bad)}")
    bad = forbidden_found(t, catalog, lead=True)
    if bad:
        reasons.append(f"album description uses forbidden placement words: {', '.join(bad)}")
    if len(re.findall(r"(?<![A-Za-z])cinematic(?![A-Za-z])", t, flags=re.IGNORECASE)) > 1:
        reasons.append("'cinematic' more than once in the album description")
    return reasons


def album_name_reasons(name: str, catalog: str) -> List[str]:
    n = (name or "").strip()
    reasons = []
    if not n:
        return ["empty name"]
    if len(n.split()) > 3:
        reasons.append("more than three words")
    if re.search(r"\bvol\b\.?", n, flags=re.IGNORECASE):
        reasons.append("contains 'Vol.'")
    if re.search(r"[:–—]|\s-\s", n):
        reasons.append("contains a colon, dash or subtitle")
    if banned_found(n):
        reasons.append("contains a banned word")
    if rules.catalog_code(catalog) == "EPP":
        hits = [w for w in rules.lane_words() if _find(w, n)]
        if hits:
            reasons.append(f"contains lane word(s): {', '.join(hits)}")
    return reasons


# ── EPP lane ───────────────────────────────────────────────────────────────────

def apply_lane(track: Dict, lane: str) -> Dict:
    """
    Lane = first keyword and first Fits tag on the track. Deterministic, in code,
    so descriptions written before the lane was confirmed pick it up unchanged.
    """
    others = {n.lower() for n in rules.lane_names()}
    kws = [k for k in split_keywords(track.get("Keywords", "")) if k.lower() not in others]
    track["Keywords"] = ", ".join(([lane] + kws)[:KEYWORD_MAX])
    body, tags = split_fits(track.get("Track Description", ""))
    if tags is not None:
        rest = [t for t in tags if t.lower() not in others]
        track["Track Description"] = join_fits(body, [lane] + rest[:2])
    return track


# ── Status ─────────────────────────────────────────────────────────────────────

def status_for(reasons: List[str]) -> str:
    return BLOCKED if reasons else PASSED


def format_time(seconds) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    return f"{int(s // 60)}:{int(round(s % 60)):02d}"


def format_events(events: List[Dict]) -> str:
    return " · ".join(f"{format_time(e.get('t'))} {e.get('what', '')}" for e in events or [])
