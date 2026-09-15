"""
The v4 analysis contract.

Analysis is Call A (Gemini listens). Field order matters: Gemini fills fields
in property order, so analysis_scratchpad comes first and the model writes its
notes before it commits to any answer. Writing is Call B (Gemini writes from
the analysis, no audio).

Instrumentation is sent to Gemini as a flat list of Observations — only the
families heard as present or uncertain. The nested 31-family schema was too
large for Gemini's structured output (400 INVALID_ARGUMENT, see GATE_FIX.md).
build_family_map() turns the list back into the full 31-family map
(Instrumentation); every unlisted family is absent. simplify(), walk_families()
and the gate read that map, never the raw list.

simplify() reduces an Analysis to the flat facts the writers, the lane
proposal and the Review screen use, plus do_not_claim: every family the model
was unsure about. Nothing in do_not_claim may be mentioned in copy.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, conlist, confloat


class Presence(str, Enum):
    present = "present"
    absent = "absent"
    uncertain = "uncertain"


class Prominence(str, Enum):
    lead = "lead"
    supporting = "supporting"
    background = "background"


class TempoBand(str, Enum):
    rubato = "rubato"
    slow = "slow"
    mid = "mid"
    fast = "fast"
    very_fast = "very_fast"


class EndingType(str, Enum):
    hard_cut = "hard_cut"
    button = "button"
    ring_out = "ring_out"
    fade_out = "fade_out"


class EnergyArc(str, Enum):
    static = "static"
    build = "build"
    build_drop_build = "build_drop_build"
    crest_then_decay = "crest_then_decay"
    waves = "waves"


class MixType(str, Enum):
    full = "FULL"
    sparse = "SPARSE"
    sde = "SDE"


class FamilyName(str, Enum):
    percussion_drum_kit = "percussion.drum_kit"
    percussion_electronic_beats = "percussion.electronic_beats"
    percussion_orchestral_percussion = "percussion.orchestral_percussion"
    percussion_trailer_impacts = "percussion.trailer_impacts"
    percussion_hand_and_world_percussion = "percussion.hand_and_world_percussion"
    strings_orchestral_strings = "strings.orchestral_strings"
    strings_solo_bowed_string = "strings.solo_bowed_string"
    strings_synth_string_pad = "strings.synth_string_pad"
    strings_harp = "strings.harp"
    strings_acoustic_guitar = "strings.acoustic_guitar"
    strings_electric_guitar = "strings.electric_guitar"
    strings_world_plucked = "strings.world_plucked"
    keys_piano = "keys_and_synths.piano"
    keys_electric_piano_or_organ = "keys_and_synths.electric_piano_or_organ"
    keys_synth_pad = "keys_and_synths.synth_pad"
    keys_synth_lead_or_arp = "keys_and_synths.synth_lead_or_arp"
    keys_pulses_and_ostinati = "keys_and_synths.pulses_and_ostinati"
    bass_live_bass = "bass.live_bass"
    bass_synth_bass = "bass.synth_bass"
    bass_drone_or_sub = "bass.drone_or_sub"
    winds_orchestral_brass = "winds.orchestral_brass"
    winds_hybrid_or_synth_brass = "winds.hybrid_or_synth_brass"
    winds_woodwinds = "winds.woodwinds"
    winds_world_wind = "winds.world_wind"
    voice_solo_voice_lyrics = "voice.solo_voice_lyrics"
    voice_solo_voice_wordless = "voice.solo_voice_wordless"
    voice_choir = "voice.choir"
    voice_vocal_chops_fx = "voice.vocal_chops_fx"
    voice_spoken_or_shouted = "voice.spoken_or_shouted"
    sound_design_textures_and_atmos = "sound_design.textures_and_atmos"
    sound_design_processed_or_reversed = "sound_design.processed_or_reversed"


class Evidence(BaseModel):
    t_start: confloat(ge=0)
    t_end: confloat(ge=0)
    what: str = Field(max_length=120)


class Observation(BaseModel):
    family: FamilyName
    presence: Literal["present", "uncertain"]  # absent families are simply not listed
    prominence: Optional[Prominence] = None    # required when present
    confidence: confloat(ge=0, le=1)
    evidence: List[Evidence] = Field(default_factory=list, max_length=2)  # 1-2 when present, empty when uncertain
    note: Optional[str] = Field(default=None, max_length=120)  # instrument name or uncertain reason


# ── The full 31-family map (built in Python, never sent to Gemini) ─────────────

class Family(BaseModel):
    presence: Presence
    prominence: Optional[Prominence] = None
    confidence: confloat(ge=0, le=1) = 0.0
    evidence: List[Evidence] = Field(default_factory=list)
    uncertain_reason: Optional[str] = None
    note: Optional[str] = None


class Percussion(BaseModel):
    drum_kit: Family
    electronic_beats: Family
    orchestral_percussion: Family
    trailer_impacts: Family
    hand_and_world_percussion: Family


class Strings(BaseModel):
    orchestral_strings: Family
    solo_bowed_string: Family
    synth_string_pad: Family
    harp: Family
    acoustic_guitar: Family
    electric_guitar: Family
    world_plucked: Family


class KeysAndSynths(BaseModel):
    piano: Family
    electric_piano_or_organ: Family
    synth_pad: Family
    synth_lead_or_arp: Family
    pulses_and_ostinati: Family


class Bass(BaseModel):
    live_bass: Family
    synth_bass: Family
    drone_or_sub: Family


class Winds(BaseModel):
    orchestral_brass: Family
    hybrid_or_synth_brass: Family
    woodwinds: Family
    world_wind: Family


class Voice(BaseModel):
    solo_voice_lyrics: Family
    solo_voice_wordless: Family
    choir: Family
    vocal_chops_fx: Family
    spoken_or_shouted: Family


class SoundDesign(BaseModel):
    textures_and_atmos: Family
    processed_or_reversed: Family


class Instrumentation(BaseModel):
    percussion: Percussion
    strings: Strings
    keys_and_synths: KeysAndSynths
    bass: Bass
    winds: Winds
    voice: Voice
    sound_design: SoundDesign


class Section(BaseModel):
    t_start: confloat(ge=0)
    t_end: confloat(ge=0)
    label: str = Field(max_length=40)
    energy: int = Field(ge=1, le=5)
    what_changes: str = Field(max_length=160)


class Ending(BaseModel):
    type: EndingType
    final_accent_t: confloat(ge=0)
    tail_seconds: confloat(ge=0)


class Tempo(BaseModel):
    band: TempoBand
    bpm_estimate: Optional[int] = Field(default=None, ge=30, le=240)
    pulse_confidence: confloat(ge=0, le=1)


class Lyrics(BaseModel):
    has_intelligible_words: bool
    language: Optional[str] = Field(default=None, max_length=30)
    sample_phrase: Optional[str] = Field(default=None, max_length=60)


class Grounding(BaseModel):
    first_sound_t: confloat(ge=0)
    loudest_moment_t: confloat(ge=0)
    quietest_stretch_t: confloat(ge=0)
    ends_with_silence_seconds: confloat(ge=0)


class Analysis(BaseModel):
    analysis_scratchpad: str = Field(max_length=900, description=(
        "Before answering: note what is audible at 0:00, at the midpoint, at the end; "
        "list the three most prominent sound sources; name any ambiguity and which taxonomy "
        "definition decides it. Plain notes, no conclusions beyond the audio."))
    mix_type: MixType
    grounding: Grounding
    tempo: Tempo
    energy_arc: EnergyArc
    sections: conlist(Section, min_length=2)  # max 10 enforced in Python (gate G2): Gemini rejects maxItems > 7 here
    ending: Ending
    instrumentation: List[Observation]  # replaces nested Instrumentation (max_length removed: Gemini rejects maxItems>7 on complex nested lists)
    lyrics: Lyrics
    hybridity_electronic_pct: int = Field(ge=0, le=100)
    dialogue_friendly: bool
    modular_edit_points_t: List[confloat(ge=0)]  # trimmed to 8 in Python (gate.parse_analysis)
    the_job: str = Field(max_length=200)
    narrative_map: str = Field(max_length=300)
    genre_tags: conlist(str, min_length=2, max_length=6)
    sounds_like_no_names: str = Field(max_length=200)


class Writing(BaseModel):
    """Call B. The three voices come first so the description can fuse them."""
    trailer_or_campaign_voice: str = Field(max_length=300)
    editor_voice: str = Field(max_length=300)
    supervisor_voice: str = Field(max_length=300)
    description: str = Field(max_length=700)
    keywords: conlist(str, min_length=12, max_length=18)
    tip: str = Field(max_length=200)


for _model in (Evidence, Observation, Family, Percussion, Strings, KeysAndSynths, Bass, Winds, Voice, SoundDesign,
               Instrumentation, Section, Ending, Tempo, Lyrics, Grounding, Analysis, Writing):
    _model.model_rebuild()

FAMILY_PATHS = [f.value for f in FamilyName]


# ── Observations → full family map ─────────────────────────────────────────────

def build_family_map(observations: List[Observation]) -> Tuple[Instrumentation, List[str]]:
    """
    The full 31-family map. Listed families take their Observation; every unlisted
    family is absent. A family listed twice keeps the higher-confidence entry;
    those family names are returned so the caller can log them.
    """
    chosen: Dict[str, Observation] = {}
    duplicates: List[str] = []
    for obs in observations:
        path = obs.family.value
        if path in chosen:
            duplicates.append(path)
            if obs.confidence <= chosen[path].confidence:
                continue
        chosen[path] = obs
    groups: Dict[str, Dict[str, Family]] = {}
    for path in FAMILY_PATHS:
        group, name = path.split(".")
        obs = chosen.get(path)
        if obs is None:
            fam = Family(presence=Presence.absent)
        else:
            fam = Family(presence=Presence(obs.presence), prominence=obs.prominence, confidence=obs.confidence,
                         evidence=list(obs.evidence), note=obs.note,
                         uncertain_reason=obs.note if obs.presence == "uncertain" else None)
        groups.setdefault(group, {})[name] = fam
    return Instrumentation.model_validate(groups), sorted(set(duplicates))


def families(a: Analysis) -> Instrumentation:
    return build_family_map(a.instrumentation)[0]


def find_observation(analysis: dict, path: str) -> Optional[dict]:
    """The listed Observation (as a dict) for a family path in a stored analysis, or None."""
    for obs in (analysis or {}).get("instrumentation") or []:
        if obs.get("family") == path:
            return obs
    return None


# ── Simplify ───────────────────────────────────────────────────────────────────

def _on(f, proms=("lead", "supporting", "background")):
    return f.presence == Presence.present and (f.prominence is None or f.prominence.value in proms)


def walk_families(inst):
    for gn, g in inst.__dict__.items():
        for fn, fam in g.__dict__.items():
            if isinstance(fam, Family):
                yield f"{gn}.{fn}", fam


def simplify(a: Analysis) -> dict:
    inst = families(a)
    p, s, k, b, w, v = (inst.percussion, inst.strings, inst.keys_and_synths, inst.bass, inst.winds, inst.voice)
    drums = (_on(p.drum_kit) or _on(p.electronic_beats)
             or _on(p.hand_and_world_percussion, ("lead", "supporting"))
             or (_on(p.orchestral_percussion, ("lead", "supporting")) and a.tempo.band != TempoBand.rubato))
    vocals = _on(v.solo_voice_lyrics) or _on(v.solo_voice_wordless) or _on(v.choir) or _on(v.vocal_chops_fx)
    strings_real = _on(s.orchestral_strings) or _on(s.solo_bowed_string)
    orchestral = strings_real or _on(w.orchestral_brass) or _on(w.woodwinds) or _on(p.orchestral_percussion)
    electronic = (_on(k.synth_pad) or _on(k.synth_lead_or_arp) or _on(b.synth_bass)
                  or _on(p.electronic_beats) or _on(s.synth_string_pad) or _on(w.hybrid_or_synth_brass))
    uncertain = [n for n, fam in walk_families(inst) if fam.presence == Presence.uncertain]
    return {
        "drums": drums, "vocals": vocals, "choir": _on(v.choir),
        "has_lyrics": a.lyrics.has_intelligible_words,
        "orchestral": orchestral, "electronic": electronic, "hybrid": orchestral and electronic,
        "tempo_band": a.tempo.band.value, "bpm": a.tempo.bpm_estimate,
        "ending_type": a.ending.type.value, "energy_arc": a.energy_arc.value,
        "dialogue_friendly": a.dialogue_friendly,
        "lead_sources": [n for n, fam in walk_families(inst)
                         if fam.presence == Presence.present and fam.prominence == Prominence.lead],
        "do_not_claim": uncertain,
    }


def family_label(path: str) -> str:
    """'percussion.drum_kit' -> 'drum kit'."""
    return path.split(".")[-1].replace("_or_", " or ").replace("_and_", " and ").replace("_", " ")
