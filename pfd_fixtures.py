"""
Shared test fixtures: a valid v4 analysis that agrees with a matching measured
waveform, plus a valid Call B writing. Used by test_gate, test_listen and
test_capture. Not a test module itself.
"""
import copy

from analysis_schema import Analysis

TITLE = "Sunny Ukulele Picnic"
FILENAME = "Sunny_Ukulele_Picnic_FULL.mp3"

# 60 s file: quiet 0–20, mid 20–40, loud 40–60; rings out for 2.5 s; 1 s of silence at the end.
MEASURED = {
    "duration": 60.0, "first_sound_t": 0.5, "loudest_t": 40.0, "quietest_t": 5.0,
    "tail_silence": 1.0, "decay_seconds": 2.5,
    "per_sec_db": [-30.0] * 20 + [-20.0] * 20 + [-10.0] * 20,
    "peaks_t": [40.0, 46.0, 52.0], "tempo_bpm": 120.0,
}


def absent():
    """Absent families are not listed: with_family(a, path, absent()) removes the observation."""
    return None


def present(prominence="supporting", t_start=20.0, t_end=40.0, what="clearly audible", confidence=0.9, note=None):
    return {"presence": "present", "prominence": prominence, "confidence": confidence,
            "evidence": [{"t_start": t_start, "t_end": t_end, "what": what}], "note": note}


def uncertain(reason="could be a synth pad or a string section"):
    return {"presence": "uncertain", "prominence": None, "confidence": 0.4, "evidence": [], "note": reason}


def with_family(a: dict, path: str, fam) -> dict:
    """Replace (or remove, when fam is None) the observation for one family."""
    a = copy.deepcopy(a)
    obs = [o for o in a["instrumentation"] if o["family"] != path]
    if fam is not None:
        obs.append({"family": path, **fam})
    a["instrumentation"] = obs
    return a


def analysis_dict(**over):
    a = {
        "analysis_scratchpad": "0:00 soft strings. 0:30 kit groove. 0:59 strings ring out. Ambiguity: pad vs strings.",
        "mix_type": "FULL",
        "grounding": {"first_sound_t": 0.5, "loudest_moment_t": 41.0, "quietest_stretch_t": 5.0,
                      "ends_with_silence_seconds": 1.0},
        "tempo": {"band": "mid", "bpm_estimate": 120, "pulse_confidence": 0.8},
        "energy_arc": "build",
        "sections": [
            {"t_start": 0.0, "t_end": 20.0, "label": "intro", "energy": 1, "what_changes": "strings alone"},
            {"t_start": 20.0, "t_end": 40.0, "label": "build", "energy": 3, "what_changes": "kit enters"},
            {"t_start": 40.0, "t_end": 59.0, "label": "peak", "energy": 5, "what_changes": "full ensemble"},
        ],
        "ending": {"type": "ring_out", "final_accent_t": 57.0, "tail_seconds": 2.5},
        "instrumentation": [
            {"family": "percussion.drum_kit", **present("lead", 20.0, 40.0, "kick and snare groove")},
            {"family": "strings.orchestral_strings", **present("supporting", 0.0, 59.0, "bowed string section")},
        ],
        "lyrics": {"has_intelligible_words": False, "language": None, "sample_phrase": None},
        "hybridity_electronic_pct": 10,
        "dialogue_friendly": False,
        "modular_edit_points_t": [20.0, 40.0],
        "the_job": "Builds pressure toward a reveal.",
        "narrative_map": "strings 0:00 → kit 0:20 → peak 0:40 → ring-out 0:57",
        "genre_tags": ["hybrid orchestral", "tension"],
        "sounds_like_no_names": "Dark string build over a tight kit, ending in a long ring-out.",
    }
    a.update(copy.deepcopy(over))
    return a


def analysis(**over) -> Analysis:
    return Analysis.model_validate(analysis_dict(**over))


KEYWORDS = [f"Tone {w}" for w in "Alpha Bravo Delta Echo Golf Hotel India Kilo Lima Mike Oscar Papa Romeo Sierra".split()]
DESCRIPTION = "Bowed strings swell under a tight kit groove. It builds to a full peak and rings out. Fits: Trailer, Film"


def writing_dict(**over):
    w = {
        "trailer_or_campaign_voice": "Act-two escalation for a reveal.",
        "editor_voice": "Clean cut points at 0:20 and 0:40.",
        "supervisor_voice": "Thriller campaigns and prestige drama.",
        "description": DESCRIPTION,
        "keywords": list(KEYWORDS),
        "tip": "Hit the 0:40 peak on the title card.",
    }
    w.update(over)
    return w
