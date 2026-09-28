"""Referee (referee.py) and structure brief (structure.py): measure-first rules, 2026-09-28."""
import referee
import structure


def _structure():
    return {"duration_s": 150.0, "sections": [0.0, 27.0, 50.0, 91.0], "stop_downs": [{"start": 80.3, "len": 0.65}],
            "hits": [16.0], "ending": {"type": "fade", "tail_len_s": 7.0, "last_hit_at": None, "end_drop_db": 50.0},
            "trajectory": "two-phase", "peak_at_s": 140, "dialogue_room_share": 0.51,
            "dialogue_sections": [[0.0, 27.0]], "tempo": "123 BPM", "bpm": 123.0, "bpm_conf": 0.9,
            "section_tempi": [{"start": 0.0, "end": 27.0, "bpm": 117}], "harmonic_share": 0.9,
            "weight_carrier": "harmonic", "evolution": "slowly evolving", "keywords": ["Ring-Out Tail"]}


def _track(title, desc, sources=None):
    return {"Title": title, "Mix Type": "Full Mix", "Track Description": desc, "structure": _structure(),
            "named_sources": sources or []}


def test_brief_lists_measured_moments():
    text = structure.brief(_structure())
    assert "0:27" in text and "1:20" in text and "0:16" in text
    assert "drums are unlikely" in text
    assert structure.event_times(_structure()) == [0.0, 16.0, 27.0, 50.0, 80.3, 91.0, 150.0]


def test_r1_flags_an_invented_timestamp_and_accepts_a_measured_one():
    good = referee.check_track(_track("A", "A drop at 1:20 opens the back end. Fits: x, y"))
    bad = referee.check_track(_track("B", "A peak at 2:20 crowns it. Fits: x, y"))
    assert not [f for f in good if f["rule"] == "R1"]
    assert [f for f in bad if f["rule"] == "R1"]


def test_r6_one_timestamp_only():
    f = referee.check_track(_track("A", "Ticks at 0:16, drops at 1:20, ends at 2:30. Fits: x"))
    assert any(x["rule"] == "R6" for x in f)


def test_r2_hedged_instrument_written_plainly():
    src = [{"family": "strings.solo_bowed_string", "heard_as": "cello", "confidence": 0.7, "write_as": "cello-like", "role": "lead"}]
    plain = referee.check_track(_track("A", "A scratchy solo cello paces at 0:27. Fits: x", src))
    hedged = referee.check_track(_track("A", "A cello-like line paces at 0:27. Fits: x", src))
    assert any(x["rule"] == "R2" for x in plain)
    assert not any(x["rule"] == "R2" for x in hedged)


def test_r3_drums_on_a_harmonic_track():
    f = referee.check_track(_track("A", "Drums land at 0:50. Fits: x"))
    assert any(x["rule"] == "R3" for x in f)


def test_r4_r5_cross_track_repeats():
    a = _track("A", "Strings climb until the floor gives way — the sound of a mind finally breaking. Fits: x")
    b = _track("B", "A tick bends time — the sound of a mind finally breaking. Fits: y")
    c = _track("C", "Something else entirely, at 0:27. Fits: z")
    album = referee.check_album([a, b, c])
    rules = {f["rule"] for f in album}
    assert "R4" in rules
    assert a["PFD_Referee"] and b["PFD_Referee"] and not c["PFD_Referee"]
    assert "reword" in referee.guidance(a["PFD_Referee"])
