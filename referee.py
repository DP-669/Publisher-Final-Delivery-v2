"""
Referee: album-level cross-checks on written text (Damir's decision 2026-09-28).

Runs after Call B, on the whole album, with no model:
  R1  a timestamp in the description that is not a measured moment (structure.event_times, ±2 s)
  R2  an instrument written plainly when named_sources says "-like" (or not present at all)
  R3  "drums"/"drum" written when the measured weight carrier says drums are unlikely
  R4  a phrase of four or more words shared with another track's description on this album
  R5  the same sentence in two descriptions
  R6  more than one timestamp in a description (PFD_RULES: one timestamp, the edit point that matters)
  R7  an instrument word written plainly with no stem behind it (PFD_RULES 0.9: stems decide names);
      only when the track carries a stems record with families

Every finding is a warning on the track (PFD_Referee); the album summary is a
list of {rule, tracks, detail}. Warnings never block; they are shown, exported,
and used to redo the write with guidance.
"""
import re
from typing import Dict, List

import structure as structure_mod

TIMESTAMP = re.compile(r"\b(\d{1,2}):(\d{2})\b")
DRUM_WORDS = re.compile(r"\b(drums?|drum kit|kick|snare)\b", re.I)
PHRASE_LEN = 4


def _body(track: Dict) -> str:
    """The description without its Fits line."""
    text = track.get("Track Description") or track.get("Gemini Description") or ""
    return re.sub(r"\n?\s*Fits:.*$", "", text, flags=re.S).strip()


def _timestamps(text: str) -> List[float]:
    return [int(m.group(1)) * 60 + int(m.group(2)) for m in TIMESTAMP.finditer(text)]


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _ngrams(words: List[str], n: int) -> set:
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def _sentences(text: str) -> List[str]:
    return [s.strip().lower() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 12]


def check_track(track: Dict) -> List[Dict]:
    out = []
    body = _body(track)
    if not body:
        return out
    structure = track.get("structure") or {}
    allowed = structure_mod.event_times(structure) if structure else []
    stamps = _timestamps(body)
    if allowed:
        for t in stamps:
            if min(abs(t - a) for a in allowed) > 2.0:
                out.append({"rule": "R1", "detail": f"{structure_mod.fmt(t)} is not a measured moment"})
    if len(stamps) > 1:
        out.append({"rule": "R6", "detail": f"{len(stamps)} timestamps; the rule is one"})
    for src in track.get("named_sources") or []:
        name = src.get("heard_as", "")
        if not name or src.get("write_as", "") == name:
            continue
        # Whole name only, so "pad" inside "string pad" is not a hit on "synth pad".
        if re.search(rf"\b{re.escape(name)}\b(?!-like)", body, re.I):
            out.append({"rule": "R2", "detail": f"'{name}' written plainly; confidence {src.get('confidence')} asks for '{src.get('write_as')}'"})
    if (structure.get("harmonic_share") or 0) >= 0.85 and DRUM_WORDS.search(body):
        out.append({"rule": "R3", "detail": f"drums written; harmonic share {structure.get('harmonic_share')} says the weight is not percussive"})
    # R7: stems decide names. Only instrument nouns, only plain (not "-like"), only when stems were read.
    import stems as stems_mod
    for word, reason in stems_mod.absent_words(track.get("stems")).items():
        if re.search(rf"\b{re.escape(word)}\b(?!-like)", body, re.I):
            out.append({"rule": "R7", "detail": f"'{word}' written plainly; {reason}"})
    return out


def check_album(tracks: List[Dict]) -> List[Dict]:
    """Cross-track repetition. Returns album-level findings and stamps PFD_Referee on every track."""
    written = [t for t in tracks if _body(t)]
    grams = {id(t): _ngrams(_words(_strip_names(t)), PHRASE_LEN) for t in written}
    sents = {id(t): set(_sentences(_body(t))) for t in written}
    per_track: Dict[int, List[Dict]] = {id(t): check_track(t) for t in written}
    album: List[Dict] = []
    for i, a in enumerate(written):
        for b in written[i + 1:]:
            shared = grams[id(a)] & grams[id(b)]
            shared = {g for g in shared if not _boring(g)}
            if shared:
                phrase = max(shared, key=len)
                finding = {"rule": "R4", "detail": f"shares '{phrase}' with {b.get('Title')}"}
                per_track[id(a)].append(finding)
                per_track[id(b)].append({"rule": "R4", "detail": f"shares '{phrase}' with {a.get('Title')}"})
                album.append({"rule": "R4", "tracks": [a.get("Title"), b.get("Title")], "detail": phrase})
            same = sents[id(a)] & sents[id(b)]
            if same:
                s = next(iter(same))
                per_track[id(a)].append({"rule": "R5", "detail": f"same sentence as {b.get('Title')}: '{s[:60]}'"})
                per_track[id(b)].append({"rule": "R5", "detail": f"same sentence as {a.get('Title')}: '{s[:60]}'"})
                album.append({"rule": "R5", "tracks": [a.get("Title"), b.get("Title")], "detail": s[:80]})
    for t in written:
        t["PFD_Referee"] = per_track[id(t)]
        for f in per_track[id(t)]:
            if f["rule"] in ("R1", "R2", "R3", "R7"):
                album.append({"rule": f["rule"], "tracks": [t.get("Title")], "detail": f["detail"]})
    return album


_BORING = {"room for dialogue", "the first minute", "of the track", "in the first", "at the end", "for the cut",
           "the back end", "leave room for", "leaves room for", "the first half", "silence at", "pause at",
           "drop at", "cut at", "space for dialogue", "under dialogue", "before the final", "the final fade"}


def _strip_names(track: Dict) -> str:
    """Instrument names two tracks legitimately share are not a repeated phrase."""
    body = _body(track)
    for src in track.get("named_sources") or []:
        for n in (src.get("write_as", ""), src.get("heard_as", "")):
            if n:
                body = re.sub(rf"\b{re.escape(n)}\b", "INSTRUMENT", body, flags=re.I)
    return body


def _boring(gram: str) -> bool:
    """Utility phrases every description is allowed to share."""
    return any(b in gram for b in _BORING) or "instrument" in gram or all(w in {"the", "a", "an", "of", "and", "to", "in", "at", "for", "it", "then", "before", "into", "with", "on"} for w in gram.split())


def guidance(findings: List[Dict]) -> str:
    """One line of redo guidance from a track's findings."""
    if not findings:
        return ""
    parts = []
    for f in findings:
        r = f["rule"]
        if r == "R1":
            parts.append(f"use only measured timestamps ({f['detail']})")
        elif r == "R2":
            parts.append(f"hedge the instrument: {f['detail']}")
        elif r == "R3":
            parts.append("no drums: write hits, strikes or accents")
        elif r in ("R4", "R5"):
            parts.append(f"reword, {f['detail']}")
        elif r == "R6":
            parts.append("keep one timestamp only")
        elif r == "R7":
            parts.append(f"name only what the stems contain: {f['detail']}")
    return "; ".join(dict.fromkeys(parts))
