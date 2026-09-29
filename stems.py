"""
stems.py — the composer's stem folder as a list of what is PRESENT in a track.

PFD_RULES v0.9 (Damir, 2026-09-29, after Vesna's SSC022 check): stem file names are the
composer's own instrument list and outrank the listener for NAMES. They say nothing about
prominence: twenty string stems and two vocal stems do not make the strings lead. Composers
stack libraries, then pull them down under the vocal. So this module reports presence only —
never counts, never weight. What leads comes from the mixed audio (structure.py + the listener).

    find_stems(root, title, mix)  → the stem folder for one track and mix, or None
    read_stems(folder)            → {"labels", "families", "source", "mix", "files", "unmapped", "anomalies"}
    apply_to_named_sources(named_sources, stems, catalog_code) → named_sources with stem-backed names
    absent_words(stems)           → instrument words the writer must not use plainly (referee R7)

Tolerant on purpose: composers misspell (Sparce, LIght, THey), leave double spaces, number
takes ("Strings 12", "Atmos1", "Bass 1_bip") and sometimes dump raw Logic bounces with the wrong
track name. Anything that carries no instrument word is listed under "unmapped", never guessed.
"""
from __future__ import annotations
import os, re
from pathlib import Path
from typing import Dict, List, Optional

AUDIO = {".aif", ".aiff", ".wav", ".flac", ".mp3", ".m4a"}

# stem word  → (family path in analysis_schema, natural name for prose)
STEM_WORDS = {
    "strings": ("strings.orchestral_strings", "strings"), "string": ("strings.orchestral_strings", "strings"),
    "violin": ("strings.solo_bowed_string", "violin"), "viola": ("strings.solo_bowed_string", "viola"),
    "cello": ("strings.solo_bowed_string", "cello"), "celli": ("strings.solo_bowed_string", "cello"),
    "harp": ("strings.harp", "harp"), "guitar": ("strings.acoustic_guitar", "guitar"),
    "bass": ("bass.live_bass", "bass"), "sub": ("bass.drone_or_sub", "sub"),
    "drone": ("bass.drone_or_sub", "drone"), "drones": ("bass.drone_or_sub", "drone"),
    "atmos": ("sound_design.textures_and_atmos", "textures"), "atmosphere": ("sound_design.textures_and_atmos", "textures"),
    "ambience": ("sound_design.textures_and_atmos", "textures"), "texture": ("sound_design.textures_and_atmos", "textures"),
    "textures": ("sound_design.textures_and_atmos", "textures"),
    "fx": ("sound_design.processed_or_reversed", "processed textures"), "riser": ("sound_design.processed_or_reversed", "processed textures"),
    "risers": ("sound_design.processed_or_reversed", "processed textures"), "whoosh": ("sound_design.processed_or_reversed", "processed textures"),
    "hit": ("percussion.trailer_impacts", "impacts"), "hits": ("percussion.trailer_impacts", "impacts"),
    "impact": ("percussion.trailer_impacts", "impacts"), "impacts": ("percussion.trailer_impacts", "impacts"),
    "boom": ("percussion.trailer_impacts", "impacts"), "booms": ("percussion.trailer_impacts", "impacts"),
    "percussion": ("percussion.orchestral_percussion", "percussion"), "perc": ("percussion.orchestral_percussion", "percussion"),
    "taiko": ("percussion.orchestral_percussion", "percussion"), "timpani": ("percussion.orchestral_percussion", "percussion"),
    "drums": ("percussion.drum_kit", "drums"), "drum": ("percussion.drum_kit", "drums"), "kit": ("percussion.drum_kit", "drums"),
    "bells": (None, "bells"), "bell": (None, "bells"), "chimes": (None, "bells"), "glock": (None, "bells"),
    "glockenspiel": (None, "bells"), "celesta": (None, "bells"), "musicbox": (None, "bells"),
    "vocal": ("voice.solo_voice_wordless", "voice"), "vocals": ("voice.solo_voice_wordless", "voice"),
    "vox": ("voice.solo_voice_wordless", "voice"), "voice": ("voice.solo_voice_wordless", "voice"),
    "voices": ("voice.solo_voice_wordless", "voice"), "choir": ("voice.choir", "choir"),
    "breath": ("voice.breath_and_body_foley", "breathing"), "breaths": ("voice.breath_and_body_foley", "breathing"),
    "pad": ("keys_and_synths.synth_pad", "pad"), "pads": ("keys_and_synths.synth_pad", "pad"),
    "synth": ("keys_and_synths.synth_lead_or_arp", "synth"), "synths": ("keys_and_synths.synth_lead_or_arp", "synth"),
    "arp": ("keys_and_synths.synth_lead_or_arp", "arpeggio"), "arps": ("keys_and_synths.synth_lead_or_arp", "arpeggio"),
    "pulse": ("keys_and_synths.pulses_and_ostinati", "pulse"), "pulses": ("keys_and_synths.pulses_and_ostinati", "pulse"),
    "ostinato": ("keys_and_synths.pulses_and_ostinati", "ostinato"),
    "piano": ("keys_and_synths.piano", "piano"), "keys": ("keys_and_synths.piano", "keys"),
    "organ": ("keys_and_synths.electric_piano_or_organ", "organ"),
    "brass": ("winds.orchestral_brass", "brass"), "horns": ("winds.orchestral_brass", "brass"), "horn": ("winds.orchestral_brass", "brass"),
    "trumpet": ("winds.orchestral_brass", "brass"), "trombone": ("winds.orchestral_brass", "brass"),
    "woodwind": ("winds.woodwinds", "woodwinds"), "woodwinds": ("winds.woodwinds", "woodwinds"),
    "flute": ("winds.woodwinds", "flute"), "clarinet": ("winds.woodwinds", "clarinet"), "oboe": ("winds.woodwinds", "oboe"),
}
NOISE = {"full", "sparse", "sparce", "sparec", "stem", "stems", "compact", "detailed", "mix", "master", "logicx", "bip", "alt"}

# Instrument words the writer may only use plainly when a stem backs them (referee R7).
INSTRUMENT_WORDS = {
    "drone": "bass.drone_or_sub", "drones": "bass.drone_or_sub", "choir": "voice.choir", "piano": "keys_and_synths.piano",
    "brass": "winds.orchestral_brass", "horns": "winds.orchestral_brass", "guitar": "strings.acoustic_guitar",
    "harp": "strings.harp", "woodwinds": "winds.woodwinds", "flute": "winds.woodwinds", "organ": "keys_and_synths.electric_piano_or_organ",
    "drums": "percussion.drum_kit", "cello": "strings.solo_bowed_string", "violin": "strings.solo_bowed_string",
    "bells": "@bells", "vocals": "voice.solo_voice_wordless", "voice": "voice.solo_voice_wordless", "choral": "voice.choir",
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _tokens(s: str) -> List[str]:
    return [t for t in re.split(r"[^a-z]+", s.lower()) if t]


def mix_of_path(p: Path) -> str:
    return "Sparse Mix" if re.search(r"spar[sc]e", str(p), re.I) else "Full Mix"


def find_stems(root: str | os.PathLike, title: str, mix: str = "Full Mix") -> Optional[Path]:
    """The stem folder for one track and mix under `root`. Compact stems win over Detailed."""
    root = Path(root)
    if not root.exists():
        return None
    want, want_mix = _norm(title), ("Sparse Mix" if "spar" in mix.lower() else "Full Mix")
    hits = []
    for d in root.rglob("*"):
        if not d.is_dir() or not any(f.suffix.lower() in AUDIO for f in d.iterdir() if f.is_file()):
            continue
        if want not in _norm(d.name) or mix_of_path(d) != want_mix:
            continue
        hits.append(d)
    if not hits:
        return None
    hits.sort(key=lambda d: (0 if "compact" in str(d).lower() else 1, len(str(d))))
    return hits[0]


def read_stems(folder: str | os.PathLike, title: str = "") -> Dict:
    """Presence only. `files` is a count for QC; it is never shown to the writer."""
    folder = Path(folder)
    files = sorted(f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in AUDIO)
    title_toks = set(_tokens(title)) if title else set()
    labels, families, unmapped, anomalies = set(), set(), [], []
    for f in files:
        toks = [t for t in _tokens(f.stem) if t not in NOISE and t not in title_toks]
        found = [STEM_WORDS[t] for t in toks if t in STEM_WORDS]
        if "string" in toks and ("hit" in toks or "hits" in toks):  # "String Hits" = strings played as strikes
            found.append(("strings.orchestral_strings", "strings"))
        if not found:
            unmapped.append(f.name)
            continue
        for fam, name in found:
            labels.add(name)
            if fam:
                families.add(fam)
    if files and len(unmapped) >= max(3, len(files) // 2):
        anomalies.append(f"{len(unmapped)} of {len(files)} stem files carry no instrument word (raw bounce?)")
    if title and files and not any(_norm(title) in _norm(f.stem) for f in files):
        anomalies.append("stem file names do not carry the track title")
    return {
        "folder": str(folder), "source": "compact" if "compact" in str(folder).lower() else "detailed",
        "mix": mix_of_path(folder), "labels": sorted(labels), "families": sorted(families),
        "files": len(files), "unmapped": unmapped[:10], "anomalies": anomalies,
    }


def stems_for(root, title: str, mix: str) -> Optional[Dict]:
    d = find_stems(root, title, mix)
    return read_stems(d, title) if d else None


def apply_to_named_sources(named: List[Dict], stems: Optional[Dict], catalog_code: str = "") -> List[Dict]:
    """A family with a stem is written plainly; a family with no stem is hedged at most.
    Prominence ('role') is left exactly as the listener heard it in the mix."""
    if not stems or not stems.get("families"):
        return named
    present = set(stems["families"])
    out = []
    for s in named:
        s = dict(s)
        fam = s.get("family", "")
        if fam in present:
            s["write_as"] = s.get("heard_as", s.get("write_as"))
            s["stem"] = "yes"
        else:
            from prompts import hedge
            s["write_as"] = hedge(s.get("heard_as", s.get("write_as", "")))
            s["stem"] = "no"
            if fam == "bass.drone_or_sub" and catalog_code == "SSC":
                s["write_as"] = "a held low note"
        out.append(s)
    return out


def absent_words(stems: Optional[Dict]) -> Dict[str, str]:
    """{word: reason} for instrument words with no stem behind them. Empty when no stems were read."""
    if not stems or not stems.get("families"):
        return {}
    present_f, present_l = set(stems["families"]), set(stems["labels"])
    out = {}
    for word, fam in INSTRUMENT_WORDS.items():
        ok = ("bells" in present_l) if fam == "@bells" else (fam in present_f)
        if not ok:
            out[word] = f"no stem for '{word}' (stems: {', '.join(stems['labels']) or 'none'})"
    return out


if __name__ == "__main__":
    import sys, json
    root, title = sys.argv[1], sys.argv[2]
    for mix in ("Full Mix", "Sparse Mix"):
        print(mix, json.dumps(stems_for(root, title, mix), indent=1))
