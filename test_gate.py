"""
Tests for the v4 gate (gate.py): G1–G16 against a fixture analysis and a
matching measured waveform, the plain-language reasons, retry hints, and the
text rules. Pure code — no models, no network.
"""
import json
import re
import unittest

import gate
from analysis_schema import Analysis, simplify
from pfd_fixtures import MEASURED, absent, analysis, analysis_dict, present, sonic_map_dict, uncertain, with_family


def check(a_dict, measured=None, mix="FULL"):
    return gate.check_analysis(Analysis.model_validate(a_dict), dict(measured or MEASURED), mix)


def rules_of(failures):
    return [f["rule"] for f in failures]


def codes(reasons):
    return {r["rule"] for r in reasons}


class TestCleanListen(unittest.TestCase):
    def test_fixture_passes_every_rule(self):
        self.assertEqual(check(analysis_dict()), [])

    def test_uncertainty_never_blocks(self):
        a = with_family(analysis_dict(), "keys_and_synths.synth_pad", uncertain())
        self.assertEqual(check(a), [])
        parsed = Analysis.model_validate(a)
        unsure = gate.uncertain_families(parsed)
        self.assertEqual(unsure, ["keys_and_synths.synth_pad"])
        self.assertEqual(gate.listen_status([], unsure), gate.PASSED_WITH_UNCERTAINTY)
        self.assertEqual(simplify(parsed)["do_not_claim"], ["keys_and_synths.synth_pad"])

    def test_status_values(self):
        self.assertEqual(gate.listen_status([], []), gate.PASSED)
        self.assertEqual(gate.listen_status([gate.failure("G5")], ["x.y"]), gate.BLOCKED)


class TestSonicMap(unittest.TestCase):
    def test_clean_map_has_no_warnings(self):
        self.assertEqual(gate.sonic_map_warnings(analysis(), 60.0), [])

    def test_late_timestamp_and_disorder_warn_but_never_block(self):
        m = sonic_map_dict()
        m["events"][1]["t"] = 70.0
        m["edit_points"] = [{"t": 61.0, "kind": "hit", "why": "past the end"}]
        a = analysis(sonic_map=m)
        warnings = gate.sonic_map_warnings(a, 60.0)
        self.assertEqual(len(warnings), 3, warnings)
        self.assertTrue(any("event 2 (answer) at 70.0 s" in w for w in warnings))
        self.assertIn("Sonic map events are not in time order.", warnings)
        self.assertEqual(gate.check_analysis(a, MEASURED, "FULL"), [])

    def test_map_needs_three_to_seven_events(self):
        m = sonic_map_dict()
        m["events"] = m["events"][:2]
        with self.assertRaises(gate.SchemaViolation):
            gate.parse_analysis(json.dumps(analysis_dict(sonic_map=m)))


class TestFamilyMap(unittest.TestCase):
    def test_unlisted_families_are_absent(self):
        from analysis_schema import FAMILY_PATHS, Presence, build_family_map, walk_families
        inst, dups = build_family_map(analysis().instrumentation)
        paths = dict(walk_families(inst))
        self.assertEqual(sorted(paths), sorted(FAMILY_PATHS))
        self.assertEqual(len(paths), 31)
        self.assertEqual(paths["percussion.drum_kit"].presence, Presence.present)
        self.assertEqual(paths["voice.choir"].presence, Presence.absent)
        self.assertEqual(dups, [])

    def test_a_family_listed_twice_keeps_the_higher_confidence(self):
        from analysis_schema import Presence, build_family_map
        a = analysis_dict()
        a["instrumentation"].append({"family": "percussion.drum_kit", **uncertain()})  # confidence 0.4 < 0.9
        a["instrumentation"].append({"family": "voice.choir", **uncertain()})
        a["instrumentation"].append({"family": "voice.choir", **present("supporting", 40, 59, "choir swells",
                                                                        confidence=0.8)})
        inst, dups = build_family_map(Analysis.model_validate(a).instrumentation)
        self.assertEqual(dups, ["percussion.drum_kit", "voice.choir"])
        self.assertEqual(inst.percussion.drum_kit.presence, Presence.present)
        self.assertEqual(inst.voice.choir.presence, Presence.present)

    def test_absent_is_not_a_legal_listed_presence(self):
        a = analysis_dict()
        a["instrumentation"].append({"family": "voice.choir", **dict(uncertain(), presence="absent")})
        with self.assertRaises(gate.SchemaViolation):
            gate.parse_analysis(json.dumps(a))

    def test_uncertain_note_becomes_the_reason(self):
        a = with_family(analysis_dict(), "strings.harp", uncertain("plucked, could be a harp or a kalimba"))
        self.assertEqual(simplify(Analysis.model_validate(a))["do_not_claim"], ["strings.harp"])
        from analysis_schema import families
        self.assertEqual(families(Analysis.model_validate(a)).strings.harp.uncertain_reason,
                         "plucked, could be a harp or a kalimba")


class TestStructure(unittest.TestCase):
    def test_g1_timestamp_past_the_end(self):
        secs = analysis_dict()["sections"]
        secs[-1]["t_end"] = 70.0
        self.assertIn("G1", rules_of(check(analysis_dict(sections=secs))))

    def test_g1_allows_half_a_second_of_slack(self):
        secs = analysis_dict()["sections"]
        secs[-1]["t_end"] = 60.4
        self.assertNotIn("G1", rules_of(check(analysis_dict(sections=secs))))

    def test_g1_backwards_evidence(self):
        a = with_family(analysis_dict(), "percussion.drum_kit", present("lead", 30.0, 20.0, "kit groove"))
        self.assertIn("G1", rules_of(check(a)))

    def test_g2_overlap(self):
        secs = analysis_dict()["sections"]
        secs[1]["t_start"] = 15.0
        self.assertIn("G2", rules_of(check(analysis_dict(sections=secs))))

    def test_g2_unordered(self):
        secs = analysis_dict()["sections"]
        secs[0], secs[1] = secs[1], secs[0]
        self.assertIn("G2", rules_of(check(analysis_dict(sections=secs))))

    def test_g2_more_than_ten_sections(self):
        secs = [{"t_start": float(i * 5), "t_end": float(i * 5 + 5), "label": f"s{i}", "energy": 3,
                 "what_changes": "x"} for i in range(12)]
        parsed = gate.parse_analysis(json.dumps(analysis_dict(sections=secs)))  # the schema no longer caps it
        failures = gate.check_sections(parsed, 60.0)
        self.assertEqual((failures[0]["rule"], failures[0]["problem"]), ("G2", "too_many"))
        x = gate.explain(failures[0])
        self.assertEqual((x["code"], x["check"], x["values"]), ("G2", "Sections", "12 sections · most allowed 10"))

    def test_edit_points_are_trimmed_to_eight_and_logged(self):
        points = [float(i) for i in range(1, 12)]
        with self.assertLogs("pfd", level="WARNING") as logs:
            parsed = gate.parse_analysis(json.dumps(analysis_dict(modular_edit_points_t=points)))
        self.assertEqual(parsed.modular_edit_points_t, points[:8])
        self.assertTrue(any("11 edit points" in m for m in logs.output))

    def test_no_list_cap_above_seven_in_the_call_a_schema(self):
        def caps(node):
            if isinstance(node, dict):
                if node.get("type") == "array" and "maxItems" in node:
                    yield node["maxItems"]
                for v in node.values():
                    yield from caps(v)
            elif isinstance(node, list):
                for v in node:
                    yield from caps(v)
        self.assertTrue(all(c <= 7 for c in caps(Analysis.model_json_schema())))

    def test_g2_coverage_under_90_percent(self):
        secs = analysis_dict()["sections"][:2]
        secs[1]["t_end"] = 30.0
        failures = check(analysis_dict(sections=secs))
        self.assertIn("G2", rules_of(failures))
        self.assertEqual(next(f for f in failures if f["rule"] == "G2")["problem"], "coverage")

    def test_g17_present_without_evidence(self):
        fam = present("lead")
        fam["evidence"] = []
        failures = check(with_family(analysis_dict(), "percussion.drum_kit", fam))
        self.assertEqual(rules_of(failures), ["G17"])  # not reported twice as G3
        self.assertEqual(failures[0]["families"], ["percussion.drum_kit"])
        hint = gate.retry_hint(failures)
        self.assertIn("percussion.drum_kit", hint)
        self.assertIn("1–2 evidence items", hint)
        x = gate.explain(failures[0])
        self.assertEqual((x["code"], x["check"]), ("G17", "Evidence"))
        self.assertEqual(x["values"], "drum kit: present with no evidence")

    def test_g3_present_with_low_confidence(self):
        fam = present("lead", confidence=0.5)
        self.assertIn("G3", rules_of(check(with_family(analysis_dict(), "percussion.drum_kit", fam))))

    def test_g3_present_without_prominence(self):
        fam = present("lead")
        fam["prominence"] = None
        self.assertIn("G3", rules_of(check(with_family(analysis_dict(), "percussion.drum_kit", fam))))

    def test_g4_schema_violation(self):
        with self.assertRaises(gate.SchemaViolation):
            gate.parse_analysis("I'm sorry, I can't analyse that file.")
        bad = analysis_dict()
        del bad["grounding"]
        with self.assertRaises(gate.SchemaViolation):
            gate.parse_analysis(json.dumps(bad))
        self.assertIsInstance(gate.parse_analysis(json.dumps(analysis_dict())), Analysis)


class TestWaveform(unittest.TestCase):
    def test_g5_first_sound(self):
        g = dict(analysis_dict()["grounding"], first_sound_t=3.0)
        self.assertIn("G5", rules_of(check(analysis_dict(grounding=g))))
        g = dict(analysis_dict()["grounding"], first_sound_t=1.9)
        self.assertNotIn("G5", rules_of(check(analysis_dict(grounding=g))))

    def test_g5_allows_up_to_one_and_a_half_seconds_of_missed_lead_in(self):
        """Loaded Gun: the model said 0.0 s, the file's first sound reads 1.5 s."""
        g = dict(analysis_dict()["grounding"], first_sound_t=0.0)
        measured = dict(MEASURED, first_sound_t=1.5325170068027212)
        self.assertNotIn("G5", rules_of(check(analysis_dict(grounding=g), measured)))
        self.assertIn("G5", rules_of(check(analysis_dict(grounding=g), dict(MEASURED, first_sound_t=1.6))))

    def test_g6_loudest_moment(self):
        g = dict(analysis_dict()["grounding"], loudest_moment_t=30.0)
        self.assertIn("G6", rules_of(check(analysis_dict(grounding=g))))

    def test_g6_near_any_top_three_peak_passes(self):
        g = dict(analysis_dict()["grounding"], loudest_moment_t=52.0)
        measured = dict(MEASURED, loudest_t=10.0, peaks_t=[10.0, 50.0, 55.0])
        self.assertNotIn("G6", rules_of(check(analysis_dict(grounding=g), measured)))

    def test_g7_tail_silence(self):
        g = dict(analysis_dict()["grounding"], ends_with_silence_seconds=4.0)
        self.assertIn("G7", rules_of(check(analysis_dict(grounding=g))))

    def test_g8_hard_cut_that_rings_out(self):
        ending = {"type": "hard_cut", "final_accent_t": 58.0, "tail_seconds": 0.0}
        failures = check(analysis_dict(ending=ending))
        self.assertIn("G8", rules_of(failures))
        f = next(x for x in failures if x["rule"] == "G8")
        x = gate.explain(f)
        self.assertEqual((x["code"], x["check"]), ("G8", "Ending"))
        self.assertEqual(x["values"], "Analysis: Hard cut · file decays for 2.5 s")
        self.assertIn("Override", x["action"])

    def test_g8_ring_out_that_stops(self):
        self.assertIn("G8", rules_of(check(analysis_dict(), dict(MEASURED, decay_seconds=0.2))))
        fade = {"type": "fade_out", "final_accent_t": 50.0, "tail_seconds": 8.0}
        self.assertIn("G8", rules_of(check(analysis_dict(ending=fade), dict(MEASURED, decay_seconds=0.2))))

    def test_g8_button_is_never_judged_on_decay(self):
        button = {"type": "button", "final_accent_t": 58.0, "tail_seconds": 0.3}
        for decay in (0.1, 3.0):
            self.assertNotIn("G8", rules_of(check(analysis_dict(ending=button), dict(MEASURED, decay_seconds=decay))))

    def test_g9_energy_shape_against_loudness(self):
        secs = analysis_dict()["sections"]
        for s, e in zip(secs, (5, 3, 1)):
            s["energy"] = e
        self.assertIn("G9", rules_of(check(analysis_dict(sections=secs))))

    def test_g9_needs_three_sections(self):
        secs = analysis_dict()["sections"][:2]
        secs[0]["energy"], secs[1]["energy"] = 5, 1
        secs[1]["t_end"] = 59.0
        self.assertNotIn("G9", rules_of(check(analysis_dict(sections=secs))))

    def _tempo(self, bpm):
        return analysis_dict(tempo={"band": "mid", "bpm_estimate": bpm, "pulse_confidence": 0.8})

    def test_g10_blocks_only_on_a_confident_tempo_far_away(self):
        self.assertIn("G10", rules_of(check(self._tempo(160))))  # 33% off 120, not a half or double

    def test_g10_ignores_a_difference_under_twenty_percent(self):
        self.assertNotIn("G10", rules_of(check(self._tempo(97))))   # 19% off
        self.assertNotIn("G10", rules_of(check(self._tempo(140))))  # 17% off

    def test_g10_ignores_half_and_double_time(self):
        for half_or_double in (60, 240, 232):  # 232 is within 10% of 240; the schema caps bpm at 240
            self.assertNotIn("G10", rules_of(check(self._tempo(half_or_double))))

    def test_g10_never_blocks_when_librosa_is_ambiguous(self):
        """Loaded Gun: librosa peaks at 68 and 136. Two candidates are ambiguity, not a hallucination."""
        ambiguous = dict(MEASURED, tempo_bpm=68.0, tempo_candidates=[68.0, 136.0], tempo_confident=False)
        with self.assertLogs("pfd", level="INFO") as logs:
            failures = check(self._tempo(120), ambiguous)
        self.assertNotIn("G10", rules_of(failures))
        self.assertTrue(any("tempo is ambiguous" in m for m in logs.output))

    def test_g10_needs_a_measured_tempo(self):
        no_tempo = dict(MEASURED, tempo_bpm=None, tempo_candidates=[], tempo_confident=False)
        self.assertNotIn("G10", rules_of(check(self._tempo(160), no_tempo)))

    def test_g10_only_with_a_groove(self):
        self.assertNotIn("G10", rules_of(check(with_family(self._tempo(160), "percussion.drum_kit", absent()))))


class TestConsistency(unittest.TestCase):
    def test_g11_groove_is_not_rubato(self):
        tempo = {"band": "rubato", "bpm_estimate": None, "pulse_confidence": 0.2}
        self.assertIn("G11", rules_of(check(analysis_dict(tempo=tempo))))

    def test_g12_words_need_a_voice(self):
        lyrics = {"has_intelligible_words": True, "language": "English", "sample_phrase": "hold on"}
        self.assertIn("G12", rules_of(check(analysis_dict(lyrics=lyrics))))
        a = with_family(analysis_dict(lyrics=lyrics), "voice.solo_voice_lyrics", present("lead", 20, 40, "lead vocal"))
        self.assertNotIn("G12", rules_of(check(a)))

    def test_g13_choir_evidence_mentions_voices(self):
        a = with_family(analysis_dict(), "voice.choir", present("supporting", 40, 59, "high shimmering strings"))
        self.assertIn("G13", rules_of(check(a)))
        a = with_family(analysis_dict(), "voice.choir", present("supporting", 40, 59, "wordless choir swells"))
        self.assertNotIn("G13", rules_of(check(a)))

    def test_g14_dialogue_friendly_has_no_lyrics(self):
        lyrics = {"has_intelligible_words": True, "language": "English", "sample_phrase": "hold on"}
        a = with_family(analysis_dict(lyrics=lyrics, dialogue_friendly=True),
                        "voice.solo_voice_lyrics", present("lead", 20, 40, "lead vocal"))
        self.assertIn("G14", rules_of(check(a)))

    def test_g15_sound_design_element_is_not_a_band(self):
        self.assertNotIn("G15", rules_of(check(analysis_dict(mix_type="SDE"), mix="SDE")))
        a = with_family(analysis_dict(mix_type="SDE"), "keys_and_synths.piano", present("supporting", 0, 30, "piano"))
        self.assertIn("G15", rules_of(check(a, mix="SDE")))
        self.assertNotIn("G15", rules_of(check(a, mix="FULL")))

    def test_g15_ignores_sound_design_and_impacts(self):
        a = analysis_dict(mix_type="SDE")
        for path in ("sound_design.textures_and_atmos", "sound_design.processed_or_reversed",
                     "percussion.trailer_impacts"):
            a = with_family(a, path, present("lead", 0, 30, "processed hit"))
        self.assertNotIn("G15", rules_of(check(a, mix="SDE")))

    def test_g16_named_artist_or_film(self):
        failures = check(analysis_dict(sounds_like_no_names="Like a Hans Zimmer Interstellar organ cue."))
        f = next(x for x in failures if x["rule"] == "G16")
        self.assertIn("Hans Zimmer", f["names"])
        self.assertIn("Interstellar", f["names"])
        self.assertNotIn("G16", rules_of(check(analysis_dict(sounds_like_no_names="Organ drone with a slow arrival."))))


class TestReasonsAndHints(unittest.TestCase):
    ALL = [gate.failure("G1", what="the 'peak' section", t=70.0, duration=60.0),
           gate.failure("G2", problem="coverage", pct=50.0), gate.failure("G3", family="voice.choir", problem="no_evidence"),
           gate.failure("G4", error="x"), gate.failure("G5", model=3.0, measured=0.5),
           gate.failure("G6", model=30.0, measured=40.0), gate.failure("G7", model=4.0, measured=1.0),
           gate.failure("G8", model="ring_out", measured=0.2), gate.failure("G9", rho=-1.0),
           gate.failure("G10", model=97, measured=120.0), gate.failure("G11"), gate.failure("G12"),
           gate.failure("G13"), gate.failure("G14"), gate.failure("G15", count=3),
           gate.failure("G16", names=["Hans Zimmer"]),
           gate.failure("G17", families=["voice.choir", "strings.harp"]), gate.failure("NO_AUDIO"),
           gate.failure("API")]

    TEXT_RULES = [gate.failure("DESC_EMPTY"), gate.failure("FITS_MISSING"), gate.failure("FITS_COUNT", count=1),
                  gate.failure("FITS_TAG", tag="Advertising", catalog="rC", legal=["Trailer", "Film"]),
                  gate.failure("FITS_LANE", lane="Sounds Tender", first="Documentary"),
                  gate.failure("SENTENCES", count=5), gate.failure("BANNED", words=["epic"]),
                  gate.failure("FORBIDDEN", words=["commercial"], catalog="rC"),
                  gate.failure("CINEMATIC_FIRST"), gate.failure("TITLE_IN_DESC", title="Glass Hours"),
                  gate.failure("THIS_TRACK"), gate.failure("KW_COUNT", count=3),
                  gate.failure("KW_LONG", keyword="one two three four"),
                  gate.failure("KW_BANNED", keyword="Epic Rise", words=["epic"]),
                  gate.failure("KW_FORBIDDEN", keyword="Advert Spot", words=["advertising"], catalog="rC"),
                  gate.failure("KW_CINEMATIC", keyword="Cinematic Swell"),
                  gate.failure("KW_LANE", lane="Sounds Tender", first="Documentary"),
                  gate.failure("WRITE", error="EOF while parsing"), gate.failure("NO_ANALYSIS"),
                  gate.failure("PARENT", title="Glass Hours", status="blocked")]

    def test_every_reason_names_the_check_the_values_and_what_to_do(self):
        for f in self.ALL + self.TEXT_RULES:
            x = gate.explain(f)
            self.assertTrue(x["code"], f)
            self.assertTrue(x["check"], f)
            self.assertTrue(x["values"], f)          # the values that disagreed
            self.assertTrue(x["meaning"], f)         # plain English
            self.assertTrue(x["action"], f)          # what to do next
            self.assertIn("What to do:", gate.export_line(f))
            self.assertTrue(gate.summary(f).startswith(f"{x['code']} · {x['check']}"), gate.summary(f))

    def test_the_gate_rules_show_their_id(self):
        """Damir's team asked for the rule ID, the values, the meaning and the instruction."""
        f = gate.failure("G10", model=120, measured=68.0, candidates=[68.0, 136.0])
        x = gate.explain(f)
        self.assertEqual((x["code"], x["check"]), ("G10", "Tempo"))
        self.assertEqual(x["values"], "Gemini: 120 BPM · librosa: 68 BPM (candidates 68, 136)")
        self.assertIn("half or double time", x["meaning"])
        self.assertIn("Override", x["action"])

    def test_legacy_string_reasons_still_read(self):
        (reason,) = gate.normalize(["duration mismatch"])
        self.assertEqual(reason["rule"], "NOTE")
        self.assertIn("Duration mismatch", gate.explain(reason)["values"])

    def test_reason_text_keeps_the_wording_the_model_is_given(self):
        self.assertEqual(gate.reason_text(gate.failure("FITS_MISSING")),
                         "description does not end with a 'Fits:' line")
        self.assertEqual(gate.reason_text(gate.failure("BANNED", words=["epic", "huge"])),
                         "description uses banned words: epic, huge")

    def test_hints_name_the_rule_but_never_the_measured_answer(self):
        hint = gate.retry_hint([gate.failure("G5", model=3.0, measured=0.5)])
        self.assertIn("first_sound_t", hint)
        self.assertNotIn("0.5", hint)
        self.assertEqual(gate.retry_hint([gate.failure("G1", what="x", t=1, duration=1), gate.failure("G4")]), "")

    def test_spearman(self):
        self.assertAlmostEqual(gate.spearman([1, 2, 3], [10, 20, 30]), 1.0)
        self.assertAlmostEqual(gate.spearman([1, 2, 3], [30, 20, 10]), -1.0)
        self.assertIsNone(gate.spearman([2, 2, 2], [1, 2, 3]))


class TestSimplify(unittest.TestCase):
    def test_timpani_in_rubato_is_not_drums(self):
        a = with_family(with_family(analysis_dict(tempo={"band": "rubato", "bpm_estimate": None, "pulse_confidence": 0.1}),
                                    "percussion.drum_kit", absent()),
                        "percussion.orchestral_percussion", present("lead", 40, 59, "timpani rolls"))
        self.assertFalse(simplify(Analysis.model_validate(a))["drums"])

    def test_kit_is_drums_and_leads_are_listed(self):
        s = simplify(analysis())
        self.assertTrue(s["drums"])
        self.assertEqual(s["lead_sources"], ["percussion.drum_kit"])
        self.assertEqual(s["ending_type"], "ring_out")


class TestTextRules(unittest.TestCase):
    def test_fits_tags_are_case_insensitive(self):
        self.assertEqual(gate.fits_reasons(["documentary", "TRAILER"], "rC"), [])
        self.assertTrue(gate.fits_reasons(["Documentary", "Advertising"], "rC"))
        self.assertEqual(gate.split_fits("A. B. Fits: documentary, Film")[1], ["documentary", "Film"])

    def test_description_rules(self):
        self.assertIn("CINEMATIC_FIRST", codes(gate.description_reasons("Cinematic swell. Ends hard. Fits: Trailer, Film", "rC")))
        r = codes(gate.description_reasons("One sentence only. Fits: Trailer", "rC"))
        self.assertIn("SENTENCES", r)
        self.assertIn("FITS_COUNT", r)
        self.assertIn("BANNED", codes(gate.description_reasons("Epic drums hit. It ends hard. Fits: Trailer, Film", "rC")))
        self.assertIn("FITS_MISSING", codes(gate.description_reasons("Low drone. It ends. No fits line here.", "rC")))

    def test_forbidden_placement_word(self):
        reasons = gate.description_reasons("Glossy pulse for a commercial cut. It ends on a button. Fits: Trailer, Film", "rC")
        bad = next(r for r in reasons if r["rule"] == "FORBIDDEN")
        self.assertIn("commercial", bad["words"])
        self.assertIn("commercial", gate.explain(bad)["values"])

    def test_ssc_trailer_only_forbidden_as_lead(self):
        body = "Strings hold a long line. Works under a trailer's quiet middle. Fits: Film, Drama"
        self.assertNotIn("FORBIDDEN", codes(gate.description_reasons(body, "SSC")))
        lead = "Trailer-ready strings rise. They end softly. Fits: Film, Drama"
        self.assertIn("FORBIDDEN", codes(gate.description_reasons(lead, "SSC")))

    def test_sentence_helper(self):
        self.assertEqual(gate.sentence("keyword count 3 (must be 12–18)"), "Keyword count 3 (must be 12–18).")


if __name__ == "__main__":
    unittest.main(verbosity=2)
