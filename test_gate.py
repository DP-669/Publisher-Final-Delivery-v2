"""
Tests for the hallucination gate: engine.analyze_track + gate.py.

Gemini is mocked at engine.genai; the real duration is patched, except in the
read_duration tests, which build a WAV with the standard library. No keys, no network.
"""
import io
import json
import struct
import unittest
import wave
from unittest.mock import MagicMock, patch

import gate
import rules
from engine import ClaudeError, IngestionEngine

REAL = 30.0
TITLE = "Sunny Ukulele Picnic"
FILENAME = "Sunny_Ukulele_Picnic_FULL.mp3"


def analysis(**over):
    a = {
        "mix_type": "FULL", "duration_seconds": 30.4, "ending_type": "Button",
        "events": [{"t": 0.0, "what": "low drone"}, {"t": 12.5, "what": "drums enter"},
                   {"t": 28.0, "what": "button hit"}],
        "facts": {"drums": True, "vocals": False, "choir": False, "tempo_band": "Mid", "energy_arc": "low to high"},
        "job": "Rising pressure for a reveal.", "narrative_map": "drone 0:00 → drums 0:12 → button 0:28",
        "trailer_or_campaign_voice": "Act two build.", "editor_voice": "Clean cut at 0:12.",
        "supervisor_voice": "Thriller campaigns.", "tip": "Tag the button ending.",
        "keywords": [f"Tone {w}" for w in "Alpha Bravo Delta Echo Golf Hotel India Kilo Lima Mike Oscar Papa Romeo Sierra".split()],
        "description": "Low drone builds under tight drums. It ends on a clean button. Fits: Trailer, Film",
    }
    a.update(over)
    return a


def verification(false=()):
    return {c: ("FALSE" if c in false else "TRUE") for c in gate.VERIFIED_CLAIMS}


class GateCase(unittest.TestCase):
    def setUp(self):
        self.engine = IngestionEngine()
        p = patch("gate.read_duration", return_value=REAL)
        self.read_duration = p.start()
        self.addCleanup(p.stop)

    def run_track(self, mock_genai, replies, catalog="rC", data=b"\xff\xfbfake-mp3"):
        client = mock_genai.Client.return_value
        client.models.generate_content.side_effect = [
            MagicMock(text=r if isinstance(r, str) else json.dumps(r)) for r in replies
        ]
        return self.engine.analyze_track(data, ".mp3", "full", catalog, "fake_key"), client


class TestAnalysisGate(GateCase):
    @patch("engine.genai")
    def test_clean_analysis_passes(self, mock_genai):
        result, client = self.run_track(mock_genai, [analysis(), verification()])
        self.assertEqual(result["status"], gate.PASSED, result["reasons"])
        self.assertEqual(client.models.generate_content.call_count, 2)

    @patch("engine.genai")
    def test_duration_mismatch_blocks(self, mock_genai):
        result, _ = self.run_track(mock_genai, [analysis(duration_seconds=45.0), verification()])
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertTrue(any("duration mismatch" in r for r in result["reasons"]), result["reasons"])

    @patch("engine.genai")
    def test_event_past_duration_blocks(self, mock_genai):
        events = [{"t": 1, "what": "a"}, {"t": 10, "what": "b"}, {"t": 95, "what": "invented climax"}]
        result, _ = self.run_track(mock_genai, [analysis(events=events), verification()])
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertTrue(any("past the end" in r for r in result["reasons"]), result["reasons"])

    @patch("engine.genai")
    def test_verification_false_twice_blocks(self, mock_genai):
        result, client = self.run_track(mock_genai, [
            analysis(), verification(false=("vocals",)),
            analysis(), verification(false=("vocals", "choir")),
        ])
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(client.models.generate_content.call_count, 4)
        joined = " ".join(result["reasons"])
        self.assertIn("vocals", joined)
        self.assertIn("choir", joined)

    @patch("engine.genai")
    def test_verification_false_once_then_true_passes(self, mock_genai):
        result, client = self.run_track(mock_genai, [
            analysis(), verification(false=("ending_type",)),
            analysis(), verification(),
        ])
        self.assertEqual(result["status"], gate.PASSED, result["reasons"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(client.models.generate_content.call_count, 4)

    @patch("engine.genai")
    def test_second_listen_audits_only_ending_vocals_choir(self, mock_genai):
        self.assertEqual(set(gate.VERIFIED_CLAIMS), {"ending_type", "vocals", "choir"})
        result, client = self.run_track(mock_genai, [analysis(), verification()])
        self.assertEqual(result["status"], gate.PASSED, result["reasons"])
        self.assertEqual(client.models.generate_content.call_count, 2)
        second = repr(client.models.generate_content.call_args_list[1].kwargs["contents"]).lower()
        for gone in ("drums", "tempo", "duration"):
            self.assertNotIn(gone, second)

    @patch("engine.genai")
    def test_schema_violation_is_a_hard_error(self, mock_genai):
        bad = analysis()
        del bad["events"]
        with self.assertRaises(gate.SchemaViolation):
            self.run_track(mock_genai, [bad, verification()])

    @patch("engine.genai")
    def test_non_json_is_a_hard_error(self, mock_genai):
        with self.assertRaises(gate.SchemaViolation):
            self.run_track(mock_genai, ["I'm sorry, I can't analyse that file."])

    @patch("engine.genai")
    def test_title_never_reaches_the_model(self, mock_genai):
        result, client = self.run_track(mock_genai, [analysis(), verification()])
        track = self.engine.track_record(TITLE, "full", result, "rC", source_path=f"/album/{FILENAME}")
        self.assertEqual(track["Title"], TITLE)  # joined afterwards, in code
        for call in client.models.generate_content.call_args_list:
            sent = repr(call.kwargs.get("contents")) + repr(call.kwargs.get("config"))
            for leak in (TITLE, FILENAME, "Sunny", "Ukulele"):
                self.assertNotIn(leak, sent)

    @patch("engine.genai")
    def test_forbidden_placement_word_blocks(self, mock_genai):
        kws = analysis()["keywords"][:-1] + ["Advertising Spot"]
        result, _ = self.run_track(mock_genai, [analysis(keywords=kws), verification()], catalog="rC")
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertTrue(any("forbidden placement" in r for r in result["reasons"]), result["reasons"])
        reasons = gate.description_reasons(
            "Glossy pulse for a commercial cut. It ends on a button. Fits: Trailer, Film", "rC")
        self.assertTrue(any("commercial" in r for r in reasons), reasons)

    @patch("engine.genai")
    def test_no_duration_blocks_without_calling_the_model(self, mock_genai):
        self.read_duration.return_value = None
        result = self.engine.analyze_track(b"garbage", ".mp3", "full", "rC", "k")
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertEqual(result["reasons"], ["no_duration"])
        mock_genai.Client.return_value.models.generate_content.assert_not_called()

    @patch("engine.genai")
    def test_call_config_is_structured_and_rule_bound(self, mock_genai):
        _, client = self.run_track(mock_genai, [analysis(), verification()], catalog="SSC")
        config = client.models.generate_content.call_args_list[0].kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertEqual(config.temperature, gate.ANALYSIS_TEMPERATURE)
        self.assertEqual(config.system_instruction, rules.system_instruction("SSC"))
        self.assertIsNotNone(config.response_schema)

    @patch("engine.genai")
    def test_large_file_uses_the_files_api(self, mock_genai):
        client = mock_genai.Client.return_value
        client.files.upload.return_value.state.name = "ACTIVE"
        big = b"\x00" * (gate.INLINE_LIMIT_BYTES + 1)
        self.run_track(mock_genai, [analysis(), verification()], data=big)
        client.files.upload.assert_called_once()
        self.assertEqual(client.files.upload.call_args.kwargs["config"].display_name, "pfd-audio")
        sent_audio = client.models.generate_content.call_args_list[0].kwargs["contents"][0]
        self.assertIs(sent_audio, client.files.upload.return_value)


class TestValidator(unittest.TestCase):
    def _track(self, description):
        engine = IngestionEngine()
        result = {"status": gate.PASSED, "reasons": [], "analysis_reasons": [], "real_duration": REAL,
                  "analysis": dict(analysis(), keywords=analysis()["keywords"]), "attempts": 1}
        track = engine.track_record("Glass Hours", "full", result, "rC")
        track["Track Description"] = description
        return engine, track

    def test_fits_tag_outside_list_fails_validator(self):
        engine, track = self._track("Low drone builds under tight drums. It ends on a clean button. Fits: Trailer, Advertising")
        data = {"tracks": [track], "album_description": "Breath and tape for slow thriller reveals.",
                "album_name_selected": "Glass Hours"}
        ok, errors = engine.validate_data(data, "rC")
        self.assertFalse(ok)
        self.assertTrue(any("not in the rC placement list" in e for e in errors), errors)
        self.assertEqual(track["PFD_Status"], gate.BLOCKED)

    def test_clean_track_passes_validator(self):
        engine, track = self._track("Low drone builds under tight drums. It ends on a clean button. Fits: Trailer, Film")
        data = {"tracks": [track], "album_description": "Breath and tape for slow thriller reveals.",
                "album_name_selected": "Tin Weather"}
        ok, errors = engine.validate_data(data, "rC")
        self.assertTrue(ok, errors)
        self.assertEqual(track["PFD_Status"], gate.PASSED)

    def test_description_rules(self):
        r = gate.description_reasons("Cinematic swell. Ends hard. Fits: Trailer, Film", "rC")
        self.assertIn("'cinematic' in the first sentence", r)
        r = gate.description_reasons("One sentence only. Fits: Trailer", "rC")
        self.assertTrue(any("sentences" in x for x in r) and any("tags" in x for x in r), r)
        r = gate.description_reasons("Epic drums hit. It ends hard. Fits: Trailer, Film", "rC")
        self.assertTrue(any("banned" in x for x in r), r)
        r = gate.description_reasons("Low drone. It ends. No fits line here.", "rC")
        self.assertIn("description does not end with a 'Fits:' line", r)

    def test_fits_tags_match_regardless_of_case_or_plural(self):
        self.assertEqual(gate.fits_reasons(["documentaries", "PRESTIGE tv"], "SSC"), [])
        self.assertEqual(gate.fits_reasons(["trailers", "tv promo", "Documentary"], "rC"), [])
        self.assertTrue(gate.fits_reasons(["Documentary", "Advertising"], "rC"))
        desc = "Strings hold a long line. They end softly. Fits: documentaries, Film"
        self.assertEqual(gate.split_fits(desc)[1], ["documentaries", "Film"])  # casing untouched

    def test_analysis_prompt_makes_the_fits_line_a_hard_requirement(self):
        import prompts
        prompt = prompts.PromptEngine().analysis_prompt("full", "SSC")
        self.assertIn("HARD REQUIREMENT", prompt)
        self.assertIn("MUST end with a Fits line", prompt)
        self.assertIn(", ".join(rules.fits_list("SSC")), prompt)

    def test_ssc_trailer_only_forbidden_as_lead(self):
        body = "Strings hold a long line. Works under a trailer's quiet middle. Fits: Film, Drama"
        self.assertFalse(any("forbidden" in r for r in gate.description_reasons(body, "SSC")))
        lead = "Trailer-ready strings rise. They end softly. Fits: Film, Drama"
        self.assertTrue(any("forbidden" in r for r in gate.description_reasons(lead, "SSC")))


class TestReadDuration(unittest.TestCase):
    def test_reads_a_real_header(self):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(struct.pack("<h", 0) * 8000 * 3)
        self.assertAlmostEqual(gate.read_duration(buf.getvalue(), ".wav"), 3.0, places=2)

    @patch("gate.shutil.which", return_value=None)
    def test_unreadable_header_without_ffprobe_is_none(self, _):
        self.assertIsNone(gate.read_duration(b"not audio at all", ".mp3"))


class TestClaudeFailuresAreNotCopy(unittest.TestCase):
    @patch("engine.anthropic")
    def test_api_error_raises(self, mock_anthropic):
        mock_anthropic.Anthropic.return_value.messages.create.side_effect = RuntimeError("overloaded")
        with self.assertRaises(ClaudeError):
            IngestionEngine().call_claude("sys", "prompt", "key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
