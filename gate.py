"""
The v4 gate.

Plain code, no model calls. It decides whether a listen (Call A) holds up
against the decoded waveform and against itself, and whether finished text
obeys PFD_RULES.md.

A track is PASSED, PASSED_WITH_UNCERTAINTY or BLOCKED.
- BLOCKED: the analysis contradicts the waveform or itself (G1–G16), or the
  finished text breaks a rule. BLOCKED always carries reasons, and they travel
  into the export. Nothing here converts BLOCKED into a result.
- PASSED_WITH_UNCERTAINTY: the listen holds up, and some instrument families
  were marked uncertain. Uncertainty never blocks; uncertain families are
  simply never mentioned in copy.

Rule IDs (G1…G16) are internal. The app shows plain_reason() sentences only.
"""
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import ValidationError

import rules
from analysis_schema import (Analysis, EndingType, Presence, TempoBand, Writing, families, family_label,
                             walk_families)

PASSED = "PASSED"
PASSED_WITH_UNCERTAINTY = "PASSED_WITH_UNCERTAINTY"
BLOCKED = "BLOCKED"
READY = (PASSED, PASSED_WITH_UNCERTAINTY)

KEYWORD_MIN, KEYWORD_MAX = 12, 18
INLINE_LIMIT_BYTES = 15 * 1024 * 1024   # larger files go through the Files API
MIX_TYPES = ("FULL", "SPARSE", "SDE")

# ── Thresholds (v4 build spec) ─────────────────────────────────────────────────
TIMESTAMP_SLACK_S = 0.5        # G1: timestamps may run 0.5 s past the end
SECTION_SLACK_S = 0.5          # G2: rounding tolerance for touching sections
SECTION_COVERAGE_MIN = 0.90    # G2
PRESENT_CONFIDENCE_MIN = 0.6   # G3
FIRST_SOUND_TOL_S = 1.5        # G5
LOUDEST_TOL_S = 6.0            # G6
TAIL_SILENCE_TOL_S = 1.5       # G7
DECAY_SPLIT_S = 1.0            # G8
ENERGY_RHO_MIN = 0.4           # G9
BPM_TOL = 0.08                 # G10
SDE_MAX_MUSICAL_FAMILIES = 2   # G15
MAX_SECTIONS = 10              # G2 (not in the schema: Gemini rejects maxItems > 7)
MAX_EDIT_POINTS = 8            # trimmed in parse_analysis
MAX_OBSERVATIONS = 20          # logged in parse_analysis

log = logging.getLogger("pfd")

STRUCTURAL_RULES = ("G1", "G2", "G3", "G4")   # re-run once, no hint
HINTED_RULES = tuple(f"G{i}" for i in range(5, 18))  # re-run once, rule named in the user text

KNOWN_NAMES_PATH = Path(__file__).resolve().parent / "reference" / "known_names.txt"


class SchemaViolation(RuntimeError):
    """The model's JSON does not match the schema (G4)."""


# ── Mix type ───────────────────────────────────────────────────────────────────

def mix_type_code(mix_type: str) -> str:
    """Map the app's mix labels ('full', 'sparse', 'sound_design', 'Sound Design') to FULL/SPARSE/SDE."""
    m = (mix_type or "").strip().lower().replace(" ", "_")
    if m in ("sparse", "sparse_mix", "sparce"):
        return "SPARSE"
    if m in ("sde", "sound_design", "sound_design_element"):
        return "SDE"
    return "FULL"


# ── Parsing ────────────────────────────────────────────────────────────────────

def _parse(model, text: str, what: str):
    try:
        return model.model_validate_json(text or "")
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:8])
        raise SchemaViolation(f"{what}: {problems}. First 200 chars: {str(text)[:200]!r}")


def parse_analysis(text: str) -> Analysis:
    """
    Validate Call A. List caps above 7 are not in the schema (Gemini rejects them);
    they are enforced here and in G2: edit points are trimmed to 8, more than 10
    sections fails G2, more than 20 observations is logged.
    """
    a = _parse(Analysis, text, "analysis")
    if len(a.modular_edit_points_t) > MAX_EDIT_POINTS:
        log.warning("Call A returned %d edit points; kept the first %d", len(a.modular_edit_points_t), MAX_EDIT_POINTS)
        a.modular_edit_points_t = a.modular_edit_points_t[:MAX_EDIT_POINTS]
    if len(a.instrumentation) > MAX_OBSERVATIONS:
        log.warning("Call A listed %d observations (spec cap %d); duplicates are merged in the family map",
                    len(a.instrumentation), MAX_OBSERVATIONS)
    return a


def parse_writing(text: str) -> Writing:
    return _parse(Writing, text, "writing")


def failure(rule: str, **detail) -> Dict:
    return {"rule": rule, **detail}


def _present(fam) -> bool:
    return fam.presence == Presence.present


# ── G1–G3: the analysis against itself ─────────────────────────────────────────

def _timestamps(a: Analysis):
    g = a.grounding
    yield "the first sound", g.first_sound_t
    yield "the loudest moment", g.loudest_moment_t
    yield "the quietest stretch", g.quietest_stretch_t
    yield "the final accent", a.ending.final_accent_t
    for s in a.sections:
        yield f"the '{s.label}' section", s.t_start
        yield f"the '{s.label}' section", s.t_end
    for t in a.modular_edit_points_t:
        yield "an edit point", t
    for obs in a.instrumentation:
        for e in obs.evidence:
            yield f"the {family_label(obs.family.value)}", e.t_start
            yield f"the {family_label(obs.family.value)}", e.t_end


def check_timestamps(a: Analysis, duration: float) -> List[Dict]:
    """G1: every timestamp inside [0, duration + 0.5]; evidence never ends before it starts."""
    limit = duration + TIMESTAMP_SLACK_S
    for what, t in _timestamps(a):
        if t < 0 or t > limit:
            return [failure("G1", what=what, t=float(t), duration=duration)]
    for obs in a.instrumentation:
        for e in obs.evidence:
            if e.t_end < e.t_start:
                return [failure("G1", what=f"the {family_label(obs.family.value)}", t=float(e.t_end),
                                duration=duration, backwards=True)]
    return []


def check_sections(a: Analysis, duration: float) -> List[Dict]:
    """G2: at most 10 sections, ordered, not overlapping, covering at least 90% of the file."""
    secs = list(a.sections)
    if len(secs) > MAX_SECTIONS:
        return [failure("G2", problem="too_many", count=len(secs))]
    for s in secs:
        if s.t_end < s.t_start:
            return [failure("G2", problem="backwards", label=s.label)]
    for prev, nxt in zip(secs, secs[1:]):
        if nxt.t_start < prev.t_start:
            return [failure("G2", problem="unordered", label=nxt.label)]
        if nxt.t_start < prev.t_end - SECTION_SLACK_S:
            return [failure("G2", problem="overlap", label=nxt.label)]
    covered = sum(max(0.0, min(s.t_end, duration) - max(s.t_start, 0.0)) for s in secs)
    pct = covered / duration if duration > 0 else 0.0
    if pct < SECTION_COVERAGE_MIN:
        return [failure("G2", problem="coverage", pct=round(100 * pct, 1))]
    return []


def check_presence(a: Analysis) -> List[Dict]:
    """G3: a present family has confidence >= 0.6 and a prominence. Missing evidence is G17."""
    out = []
    for path, fam in walk_families(families(a)):
        if not _present(fam) or not fam.evidence:
            continue
        if fam.confidence < PRESENT_CONFIDENCE_MIN:
            out.append(failure("G3", family=path, problem="low_confidence", confidence=float(fam.confidence)))
        elif fam.prominence is None:
            out.append(failure("G3", family=path, problem="no_prominence"))
    return out


def check_observations(a: Analysis) -> List[Dict]:
    """G17: an Observation listed as present with no evidence. Re-run once, naming the families."""
    missing = sorted({o.family.value for o in a.instrumentation if o.presence == "present" and not o.evidence})
    return [failure("G17", families=missing)] if missing else []


# ── G5–G10: the analysis against the waveform ──────────────────────────────────

def spearman(x: List[float], y: List[float]) -> Optional[float]:
    """Spearman rank correlation with average ranks for ties. None when either side is constant."""
    if len(x) != len(y) or len(x) < 2:
        return None

    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r

    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(rx, ry)) / (sxx * syy) ** 0.5


def section_loudness(a: Analysis, per_sec_db: List[float]) -> List[Optional[float]]:
    out = []
    for s in a.sections:
        lo, hi = int(s.t_start), max(int(s.t_start) + 1, int(-(-s.t_end // 1)))
        vals = per_sec_db[lo:hi]
        out.append(sum(vals) / len(vals) if vals else None)
    return out


def check_waveform(a: Analysis, m: Dict) -> List[Dict]:
    out = []
    g = a.grounding

    if abs(g.first_sound_t - m["first_sound_t"]) > FIRST_SOUND_TOL_S:
        out.append(failure("G5", model=float(g.first_sound_t), measured=m["first_sound_t"]))

    peaks = m.get("peaks_t") or []
    if (abs(g.loudest_moment_t - m["loudest_t"]) > LOUDEST_TOL_S
            and all(abs(g.loudest_moment_t - p) > LOUDEST_TOL_S for p in peaks)):
        out.append(failure("G6", model=float(g.loudest_moment_t), measured=m["loudest_t"]))

    if abs(g.ends_with_silence_seconds - m["tail_silence"]) > TAIL_SILENCE_TOL_S:
        out.append(failure("G7", model=float(g.ends_with_silence_seconds), measured=m["tail_silence"]))

    decay = m["decay_seconds"]
    if a.ending.type == EndingType.hard_cut and decay > DECAY_SPLIT_S:
        out.append(failure("G8", model=a.ending.type.value, measured=decay))
    elif a.ending.type in (EndingType.ring_out, EndingType.fade_out) and decay < DECAY_SPLIT_S:
        out.append(failure("G8", model=a.ending.type.value, measured=decay))

    if len(a.sections) >= 3:
        loud = section_loudness(a, m.get("per_sec_db") or [])
        pairs = [(s.energy, l) for s, l in zip(a.sections, loud) if l is not None]
        if len(pairs) >= 3:
            rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
            if rho is not None and rho < ENERGY_RHO_MIN:
                out.append(failure("G9", rho=round(rho, 2)))

    p = families(a).percussion
    bpm, measured_bpm = a.tempo.bpm_estimate, m.get("tempo_bpm")
    if ((_present(p.drum_kit) or _present(p.electronic_beats)) and bpm and measured_bpm
            and a.tempo.band != TempoBand.rubato):
        if not any(abs(c - measured_bpm) <= BPM_TOL * measured_bpm for c in (bpm, bpm / 2, bpm * 2)):
            out.append(failure("G10", model=bpm, measured=measured_bpm))
    return out


# ── G11–G16: consistency ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def known_names() -> tuple:
    if not KNOWN_NAMES_PATH.exists():
        return ()
    lines = KNOWN_NAMES_PATH.read_text(encoding="utf-8").splitlines()
    return tuple(l.strip() for l in lines if l.strip() and not l.startswith("#"))


def names_found(text: str) -> List[str]:
    return [n for n in known_names() if _find(n, text or "")]


def check_consistency(a: Analysis, mix_code: str) -> List[Dict]:
    out = []
    inst = families(a)
    p, v = inst.percussion, inst.voice
    groove = _present(p.drum_kit) or _present(p.electronic_beats)

    if groove and a.tempo.band == TempoBand.rubato:
        out.append(failure("G11"))
    if a.lyrics.has_intelligible_words and not (_present(v.solo_voice_lyrics) or _present(v.choir)):
        out.append(failure("G12"))
    if _present(v.choir) and not any(re.search(r"voice|vocal|choir", e.what, flags=re.IGNORECASE)
                                     for e in v.choir.evidence):
        out.append(failure("G13"))
    if a.dialogue_friendly and _present(v.solo_voice_lyrics):
        out.append(failure("G14"))
    if mix_code == "SDE":
        musical = [path for path, fam in walk_families(inst)
                   if _present(fam) and not path.startswith("sound_design.")
                   and path != "percussion.trailer_impacts"]
        if len(musical) > SDE_MAX_MUSICAL_FAMILIES:
            out.append(failure("G15", count=len(musical)))
    names = names_found(a.sounds_like_no_names)
    if names:
        out.append(failure("G16", names=names))
    return out


def check_analysis(a: Analysis, measured: Dict, mix_code: str) -> List[Dict]:
    """Every rule that applies to a parsed analysis. Empty list = the listen holds up."""
    duration = measured["duration"]
    return (check_timestamps(a, duration) + check_sections(a, duration) + check_presence(a)
            + check_waveform(a, measured) + check_consistency(a, mix_code) + check_observations(a))


def uncertain_families(a: Analysis) -> List[str]:
    return [path for path, fam in walk_families(families(a)) if fam.presence == Presence.uncertain]


def listen_status(failures: List[Dict], uncertain: List[str]) -> str:
    if failures:
        return BLOCKED
    return PASSED_WITH_UNCERTAINTY if uncertain else PASSED


# ── Retry hints (to the model) ─────────────────────────────────────────────────

_HINTS = {
    "G5": "first_sound_t did not match the file (off by more than 1.5 s). Listen to the opening again.",
    "G6": "loudest_moment_t is not near any of the loudest moments in the file.",
    "G7": "ends_with_silence_seconds did not match the file (off by more than 1.5 s).",
    "G8": "ending.type contradicts how the sound decays at the end of the file.",
    "G9": "the section energies do not follow the loudness shape of the file.",
    "G10": "bpm_estimate does not match the beat in the file.",
    "G11": "a drum kit or electronic beats were reported present with tempo band rubato.",
    "G12": "intelligible words were reported, but neither solo_voice_lyrics nor choir is present.",
    "G13": "choir was reported present, but its evidence does not describe voices.",
    "G14": "dialogue_friendly was true while solo_voice_lyrics is present.",
    "G15": "this is a sound design element, but more than two families outside sound_design and "
           "trailer_impacts were reported present.",
    "G16": "sounds_like_no_names named a real artist, composer or film. Describe the sound without names.",
}


def retry_hint(failures: List[Dict]) -> str:
    """User-text addendum for a re-run. Names the failed rules; never gives the measured answer."""
    lines = []
    for f in failures:
        if f["rule"] == "G17":
            hint = ("these families were listed as present with no evidence: " + ", ".join(f.get("families") or [])
                    + ". Every present family needs 1–2 evidence items; if you cannot point to it, mark it uncertain.")
        else:
            hint = _HINTS.get(f["rule"])
        if hint and hint not in lines:
            lines.append(hint)
    if not lines:
        return ""
    return "A previous listen to this file was rejected because: " + " ".join(lines) + \
        " Listen to the whole file again and answer only from the audio."


# ── Plain-language reasons (to the user) ───────────────────────────────────────

def _s(seconds) -> str:
    return f"{float(seconds):.1f}"


def plain_reason(f: Dict) -> str:
    r = f.get("rule")
    if r == "G1":
        if f.get("backwards"):
            return f"It placed {f['what']} so that it ends before it starts."
        return f"It put {f['what']} at {_s(f['t'])} s, but the file is only {_s(f['duration'])} seconds long."
    if r == "G2":
        return {
            "too_many": f"It split the track into {f.get('count')} sections; the most allowed is {MAX_SECTIONS}.",
            "backwards": "One of its sections ends before it starts.",
            "unordered": "Its sections are out of order.",
            "overlap": "Two of its sections overlap, so its map of the track can't be trusted.",
            "coverage": f"Its sections only cover {f.get('pct', 0):.0f}% of the track.",
        }.get(f.get("problem"), "Its map of the track's sections doesn't hold together.")
    if r == "G3":
        name = family_label(f.get("family", ""))
        return {
            "no_evidence": f"It said there is {name} but didn't point to where you can hear it.",
            "low_confidence": f"It said there is {name} but wasn't confident enough to claim it.",
            "no_prominence": f"It said there is {name} but not how prominent it is in the mix.",
        }.get(f.get("problem"), f"Its claim about {name} doesn't hold together.")
    if r == "G4":
        return "The analysis came back incomplete, twice."
    if r == "G5":
        return f"It said the first sound is at {_s(f['model'])} s, but the file's first sound is at {_s(f['measured'])} s."
    if r == "G6":
        return f"It said the loudest moment is at {_s(f['model'])} s, but the file peaks at {_s(f['measured'])} s."
    if r == "G7":
        return (f"It said the file ends with {_s(f['model'])} seconds of silence, "
                f"but there are {_s(f['measured'])} seconds.")
    if r == "G8":
        if f["model"] == "hard_cut":
            return f"It said the track ends with a hard cut, but the file rings out for {_s(f['measured'])} seconds."
        verb = "fades out" if f["model"] == "fade_out" else "rings out"
        return f"It said the track {verb}, but the sound stops within {_s(f['measured'])} seconds."
    if r == "G9":
        return "Its loud and quiet sections don't match the file's actual loudness."
    if r == "G10":
        return f"It heard about {f['model']} BPM, but the beat in the file is closer to {float(f['measured']):.0f} BPM."
    if r == "G11":
        return "It said there is a drum groove but also that the track has no steady tempo."
    if r == "G12":
        return "It said there are sung words but found no lead voice or choir."
    if r == "G13":
        return "It said there is a choir, but what it pointed to doesn't sound like voices."
    if r == "G14":
        return "It said the track leaves room for dialogue, but there are sung lyrics."
    if r == "G15":
        return f"This is a sound design element, but it heard {f.get('count')} instrument parts."
    if r == "G16":
        return f"It compared the track to a real artist or film ({', '.join(f.get('names') or [])})."
    if r == "G17":
        names = [family_label(p) for p in f.get("families") or []]
        if len(names) == 1:
            return f"It said there is {names[0]} but didn't point to where you can hear it."
        return f"It said there is {', '.join(names)} but didn't point to where you can hear them."
    if r == "NO_AUDIO":
        return "The file couldn't be opened to measure it."
    if r == "API":
        return "The listen didn't finish — the analysis service returned an error."
    return sentence(f.get("text") or "Something went wrong with this track.")


def sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    t = t[0].upper() + t[1:]
    return t if t[-1] in ".!?" else t + "."


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


def fits_reasons(tags: Optional[List[str]], catalog: str, lane: Optional[str] = None) -> List[str]:
    """Tags are compared case-insensitively (both sides lowercased); the text keeps its casing."""
    if tags is None:
        return ["description does not end with a 'Fits:' line"]
    reasons = []
    if not 2 <= len(tags) <= 3:
        reasons.append(f"Fits line has {len(tags)} tags (must be 2–3)")
    legal = {t.lower() for t in rules.fits_list(catalog)}
    is_epp = rules.catalog_code(catalog) == "EPP"
    lane_names = {n.lower() for n in rules.lane_names()}
    for i, tag in enumerate(tags):
        if is_epp and i == 0 and (tag.lower() == (lane or "").lower() or (not lane and tag.lower() in lane_names)):
            continue
        if tag.lower() not in legal:
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


# ── Display helpers ────────────────────────────────────────────────────────────

def status_for(reasons: List[str]) -> str:
    return BLOCKED if reasons else PASSED


ENDING_LABELS = {"hard_cut": "Hard cut", "button": "Button", "ring_out": "Ring-out", "fade_out": "Fade-out"}


def format_time(seconds) -> str:
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return ""
    return f"{int(s // 60)}:{int(round(s % 60)):02d}"


def format_sections(sections: List[Dict]) -> str:
    return " · ".join(f"{format_time(s.get('t_start'))} {s.get('label', '')}" for s in sections or [])
