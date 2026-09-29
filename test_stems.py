"""stems.py — the composer's stem names decide instrument names; presence only, never prominence."""
from pathlib import Path

import referee
import stems


def _mk(tmp_path: Path, rel: str, names):
    d = tmp_path / rel
    d.mkdir(parents=True)
    for n in names:
        (d / n).touch()
    return d


def test_reads_compact_stems_with_typos(tmp_path):
    _mk(tmp_path, "01 Compact Stems/01 Full Mix/Frozen In Motion Compact Stems",
        ["Frozen In Motion Full Stems 1 Strings.aif", "Frozen In Motion Full stems 2 Atmos.aif",
         "Frozen In Motion Full Stems 4 Vocals.aif", "Frozen In Motion Full Stems 5 Bass.aif"])
    _mk(tmp_path, "01 Compact Stems/02 Sparse Mix/Frozen In Motion Compact Sparce Stems",
        ["Frozen In Motion Sparce Stems 1 Strings.aif", "Frozen In Motion Sparce Stems 5 Bass.aif"])
    full = stems.stems_for(tmp_path, "Frozen In Motion", "Full Mix")
    sparse = stems.stems_for(tmp_path, "Frozen In Motion", "Sparse Mix")
    assert full["labels"] == ["bass", "strings", "textures", "voice"]
    assert "voice.solo_voice_wordless" in full["families"] and "bass.drone_or_sub" not in full["families"]
    assert sparse["labels"] == ["bass", "strings"] and sparse["mix"] == "Sparse Mix"


def test_detailed_take_numbers_and_bip_suffix(tmp_path):
    _mk(tmp_path, "02 Detailed Stems/01 Full Mix/Within The Mist Detailed Stems",
        ["Within THe Mist Strings 1_bip.aif", "Within The Mist Atmos 13.aif", "Within The Mist String Hits 2.aif"])
    s = stems.stems_for(tmp_path, "Within The Mist", "Full Mix")
    assert s["source"] == "detailed"
    assert s["labels"] == ["impacts", "strings", "textures"]
    assert "files" in s and s["files"] == 3  # a QC count, never shown to the writer


def test_raw_logic_dump_is_not_guessed(tmp_path):
    _mk(tmp_path, "02 Detailed Stems/01 Full Mix/Fields Of Elysium Detailed Stems",
        [f"Warriors Path stems_{i}.logicx.wav" for i in range(6)])
    s = stems.stems_for(tmp_path, "Fields Of Elysium", "Full Mix")
    assert s["families"] == [] and s["labels"] == []
    assert s["anomalies"]
    assert stems.absent_words(s) == {}  # no stems read → the rule does not fire


def test_compact_wins_over_detailed(tmp_path):
    _mk(tmp_path, "02 Detailed Stems/01 Full Mix/Stardust Detailed Stems", ["Stardust Strings 1.aif", "Stardust Piano 1.aif"])
    _mk(tmp_path, "01 Compact Stems/01 Full Mix/Stardust Compact Stems", ["Stardust Full Stems 1 Strings.aif"])
    assert stems.stems_for(tmp_path, "Stardust", "Full Mix")["source"] == "compact"


def test_apply_to_named_sources_keeps_roles_and_hedges_missing():
    st = {"families": ["strings.orchestral_strings", "bass.live_bass"], "labels": ["bass", "strings"]}
    named = [
        {"family": "strings.orchestral_strings", "heard_as": "strings", "confidence": 0.7, "write_as": "strings-like", "role": "supporting"},
        {"family": "voice.choir", "heard_as": "choir", "confidence": 0.95, "write_as": "choir", "role": "lead"},
        {"family": "bass.drone_or_sub", "heard_as": "drone", "confidence": 0.95, "write_as": "drone", "role": "supporting"},
    ]
    out = stems.apply_to_named_sources(named, st, "SSC")
    by = {o["family"]: o for o in out}
    assert by["strings.orchestral_strings"]["write_as"] == "strings"        # stem present → plain, even at 0.7
    assert by["voice.choir"]["write_as"] == "choir-like"                    # no stem → hedged, even at 0.95
    assert by["bass.drone_or_sub"]["write_as"] == "a held low note"        # SSC: no Drone stem → no "drone"
    assert by["voice.choir"]["role"] == "lead"                              # prominence untouched: stems ≠ weight


def test_referee_r7_flags_plain_instrument_without_stem():
    st = {"families": ["strings.orchestral_strings", "bass.live_bass"], "labels": ["bass", "strings"]}
    track = {"Track Description": "Ticking and a low pulse, then a choir at 1:12 over a drone. Strings drive it.",
             "stems": st, "structure": {}, "named_sources": []}
    rules = {f["rule"] for f in referee.check_track(track)}
    assert "R7" in rules
    details = " ".join(f["detail"] for f in referee.check_track(track) if f["rule"] == "R7")
    assert "'choir'" in details and "'drone'" in details
    ok = {"Track Description": "Ticking and a low pulse; strings drive it, choir-like tones above.", "stems": st,
          "structure": {}, "named_sources": []}
    assert not [f for f in referee.check_track(ok) if f["rule"] == "R7"]
