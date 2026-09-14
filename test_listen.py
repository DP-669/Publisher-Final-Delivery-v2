"""
Tests for the v4 listen → gate → write path in engine.py.

Gemini is mocked at engine.genai and the waveform measurement is patched with
the fixture, so no audio is decoded and nothing touches the network. Claude is
absent unless a test patches call_claude.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import gate
import rules
from analysis_schema import Analysis, Writing
from engine import CALL_A_CONFIG, CALL_B_CONFIG, IngestionEngine
from pfd_fixtures import (DESCRIPTION, FILENAME, MEASURED, TITLE, analysis_dict, uncertain, with_family,
                          writing_dict)
from prompts import WRITER_GROUNDING

AUDIO = b"\xff\xfbaudio-bytes"


def reply(obj):
    return MagicMock(text=obj if isinstance(obj, str) else json.dumps(obj))


class ListenCase(unittest.TestCase):
    def setUp(self):
        self.engine = IngestionEngine()
        p = patch("engine.waveform.measure_bytes", return_value=dict(MEASURED))
        self.measure = p.start()
        self.addCleanup(p.stop)
        g = patch("engine.genai")
        self.genai = g.start()
        self.addCleanup(g.stop)
        n = patch("dropbox_pipeline.send_ntfy")
        n.start()
        self.addCleanup(n.stop)
        self.client = self.genai.Client.return_value

    def replies(self, *items):
        self.client.models.generate_content.side_effect = [i if isinstance(i, Exception) else reply(i) for i in items]

    def calls(self):
        return self.client.models.generate_content.call_args_list

    def process(self, catalog="rC", **kwargs):
        return self.engine.process_track(TITLE, "full", AUDIO, ".mp3", catalog, "gemini-key", "",
                                         source_path=f"/album/{FILENAME}", **kwargs)


class TestListen(ListenCase):
    def test_clean_listen_passes_in_one_call(self):
        self.replies(analysis_dict())
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual(result["status"], gate.PASSED)
        self.assertEqual((result["attempts"], len(self.calls())), (1, 1))

    def test_waveform_failure_reruns_with_the_rule_named(self):
        bad = analysis_dict(grounding=dict(analysis_dict()["grounding"], first_sound_t=5.0))
        self.replies(bad, analysis_dict())
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual((result["status"], result["attempts"]), (gate.PASSED, 2))
        second_user_text = self.calls()[1].kwargs["contents"][1]
        self.assertIn("first_sound_t", second_user_text)
        self.assertNotIn("0.5 s", second_user_text.split("Report the analysis.")[1])
        first_user_text = self.calls()[0].kwargs["contents"][1]
        self.assertNotIn("rejected", first_user_text)

    def test_second_failure_blocks_and_stops_at_two_calls(self):
        bad = analysis_dict(grounding=dict(analysis_dict()["grounding"], first_sound_t=5.0))
        self.replies(bad, bad, analysis_dict())
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertEqual([f["rule"] for f in result["failures"]], ["G5"])
        self.assertEqual(len(self.calls()), 2)

    def test_schema_violation_reruns_once_without_a_hint(self):
        self.replies("not json at all", analysis_dict())
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual((result["status"], result["attempts"]), (gate.PASSED, 2))
        self.assertNotIn("rejected", self.calls()[1].kwargs["contents"][1])

    def test_schema_violation_twice_blocks(self):
        self.replies("{}", "{}")
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual(result["status"], gate.BLOCKED)
        self.assertEqual(result["failures"][0]["rule"], "G4")

    def test_undecodable_file_blocks_without_calling_the_model(self):
        self.measure.side_effect = RuntimeError("could not decode")
        result = self.engine.listen(b"garbage", ".mp3", "full", "k")
        self.assertEqual(result["failures"][0]["rule"], "NO_AUDIO")
        self.client.models.generate_content.assert_not_called()

    def test_uncertainty_passes_with_a_note(self):
        self.replies(with_family(analysis_dict(), "keys_and_synths.synth_pad", uncertain()))
        result = self.engine.listen(AUDIO, ".mp3", "full", "k")
        self.assertEqual(result["status"], gate.PASSED_WITH_UNCERTAINTY)
        self.assertEqual(result["simple"]["do_not_claim"], ["keys_and_synths.synth_pad"])

    def test_call_a_config_and_context(self):
        self.replies(analysis_dict())
        self.engine.listen(AUDIO, ".mp3", "sparse", "k")
        call = self.calls()[0]
        config = call.kwargs["config"]
        self.assertIs(config.response_schema, Analysis)
        self.assertEqual((config.temperature, config.top_p, config.top_k, config.candidate_count,
                          config.max_output_tokens), (0.0, 1.0, 1, 1, 6000))
        self.assertEqual(config.system_instruction, self.engine.prompts.call_a_system(60.0))
        self.assertIn("Duration of this file: 60.0 seconds", config.system_instruction)
        self.assertEqual(call.kwargs["contents"][1],
                         "Mix type: SPARSE. Duration: 60.0 s. Listen to the whole file. Report the analysis.")
        for catalog_word in ("redCola", "Short Story", "Ekonomic", "PFD RULES", "Trailer"):
            self.assertNotIn(catalog_word, config.system_instruction + call.kwargs["contents"][1])

    def test_the_audio_is_actually_sent_as_bytes(self):
        self.replies(analysis_dict())
        self.engine.listen(AUDIO, ".mp3", "full", "k")
        part = self.calls()[0].kwargs["contents"][0]
        self.assertEqual((part.inline_data.mime_type, part.inline_data.data), ("audio/mpeg", AUDIO))

    def test_large_file_uses_the_files_api(self):
        self.client.files.upload.return_value.state.name = "ACTIVE"
        self.replies(analysis_dict())
        self.engine.listen(b"\x00" * (gate.INLINE_LIMIT_BYTES + 1), ".mp3", "full", "k")
        self.client.files.upload.assert_called_once()
        self.assertEqual(self.client.files.upload.call_args.kwargs["config"].display_name, "pfd-audio")
        self.assertIs(self.calls()[0].kwargs["contents"][0], self.client.files.upload.return_value)


class TestProcessTrack(ListenCase):
    def test_listen_then_write(self):
        self.replies(analysis_dict(), writing_dict())
        track = self.process()
        self.assertEqual(track["PFD_Status"], gate.PASSED, track["PFD_Block_Reasons"])
        self.assertEqual(track["Track Description"], DESCRIPTION)  # no Claude key: Gemini's text is kept...
        self.assertIn("Not checked by Claude.", track["PFD_Notes"])  # ...and says so
        self.assertEqual(len(gate.split_keywords(track["Keywords"])), 14)
        self.assertEqual(track["Ending Type"], "Ring-out")
        self.assertEqual(len(self.calls()), 2)

    def test_call_b_config_and_prompt(self):
        ssc_description = "Bowed strings swell over a steady kit. They build to a full peak and ring out. Fits: Film, Drama"
        self.replies(with_family(analysis_dict(), "keys_and_synths.synth_pad", uncertain()),
                     writing_dict(description=ssc_description))
        track = self.process(catalog="SSC")
        call = self.calls()[1]
        config, prompt = call.kwargs["config"], call.kwargs["contents"]
        self.assertIs(config.response_schema, Writing)
        self.assertEqual((config.temperature, config.top_p, config.max_output_tokens), (0.7, 0.95, 2500))
        self.assertEqual(config.system_instruction, rules.system_instruction("SSC"))
        self.assertIn(WRITER_GROUNDING, prompt)
        self.assertIn("keys_and_synths.synth_pad", prompt.split("do_not_claim:")[1])
        self.assertNotIn("analysis_scratchpad", prompt)
        self.assertNotIn(analysis_dict()["analysis_scratchpad"], prompt)
        self.assertEqual(track["PFD_Status"], gate.PASSED_WITH_UNCERTAINTY)

    def test_blocked_listen_is_not_written(self):
        bad = analysis_dict(ending={"type": "hard_cut", "final_accent_t": 58.0, "tail_seconds": 0.0})
        self.replies(bad, bad)
        track = self.process()
        self.assertEqual(track["PFD_Status"], gate.BLOCKED)
        self.assertEqual(track["PFD_Reason_Kind"], "listen")
        self.assertEqual(track["PFD_Block_Reasons"],
                         ["It said the track ends with a hard cut, but the file rings out for 2.5 seconds."])
        self.assertEqual(len(self.calls()), 2)

    def test_title_never_reaches_a_model(self):
        self.replies(analysis_dict(), writing_dict())
        track = self.process()
        self.assertEqual(track["Title"], TITLE)
        for call in self.calls():
            sent = repr(call.kwargs.get("contents")) + repr(call.kwargs.get("config"))
            for leak in (TITLE, FILENAME, "Sunny", "Ukulele"):
                self.assertNotIn(leak, sent)

    def test_claude_gates_when_available(self):
        self.replies(analysis_dict(), writing_dict())
        gated = "Bowed strings swell under a tight kit. It builds and rings out. Fits: Trailer, Film"
        with patch.object(IngestionEngine, "call_claude", return_value=gated) as claude:
            track = self.engine.process_track(TITLE, "full", AUDIO, ".mp3", "rC", "g", "c")
        self.assertEqual(track["Track Description"], gated)
        self.assertIn(WRITER_GROUNDING, claude.call_args.args[1])
        self.assertEqual(track["PFD_Notes"], [])

    def test_text_rule_failure_is_red_with_a_text_reason(self):
        self.replies(analysis_dict(), writing_dict(description="Epic strings. It rings out. Fits: Trailer, Film"))
        track = self.process()
        self.assertEqual((track["PFD_Status"], track["PFD_Reason_Kind"]), (gate.BLOCKED, "text"))
        self.assertTrue(any("banned" in r for r in track["PFD_Block_Reasons"]))

    def test_quota_error_while_writing_stops_the_run(self):
        self.replies(analysis_dict(), RuntimeError("429 RESOURCE_EXHAUSTED"))
        with self.assertRaises(RuntimeError):
            self.process()


class TestFixActions(ListenCase):
    def test_tell_it_whats_true_marks_passed_with_a_note(self):
        bad = analysis_dict(grounding=dict(analysis_dict()["grounding"], first_sound_t=5.0))
        self.replies(bad, bad, writing_dict())
        track = self.process(correction="The strings start straight away.")
        self.assertIn("The strings start straight away.", self.calls()[0].kwargs["contents"][1])
        self.assertEqual(track["PFD_Status"], gate.PASSED, track["PFD_Block_Reasons"])
        self.assertEqual(track["PFD_Gate"]["override_note"], "Corrected by editor: The strings start straight away.")

    def test_add_it_rewrites_without_listening_again(self):
        self.replies(with_family(analysis_dict(), "keys_and_synths.synth_pad", uncertain()), writing_dict(),
                     writing_dict())
        track = self.process()
        self.assertEqual(track["PFD_Status"], gate.PASSED_WITH_UNCERTAINTY)
        self.engine.add_family(track, "keys_and_synths.synth_pad", "rC", "g", "")
        self.assertEqual(len(self.calls()), 3)
        self.assertIs(self.calls()[2].kwargs["config"].response_schema, Writing)
        self.assertEqual(track["simple"]["do_not_claim"], [])
        self.assertEqual(track["analysis"]["instrumentation"]["keys_and_synths"]["synth_pad"]["presence"], "present")
        self.assertEqual(track["PFD_Status"], gate.PASSED)

    def test_leave_it_out_clears_the_note(self):
        self.replies(with_family(analysis_dict(), "keys_and_synths.synth_pad", uncertain()), writing_dict())
        track = self.process()
        self.engine.dismiss_family(track, "keys_and_synths.synth_pad", "rC")
        self.assertEqual(track["PFD_Status"], gate.PASSED)

    def test_ill_write_it(self):
        bad = analysis_dict(grounding=dict(analysis_dict()["grounding"], first_sound_t=5.0))
        self.replies(bad, bad, writing_dict())
        track = self.process()
        self.assertEqual(track["PFD_Status"], gate.BLOCKED)
        problems = self.engine.manual_description(track, "Too short. Fits: Trailer", "rC", "g")
        self.assertTrue(problems)
        self.assertFalse(track.get("PFD_Manual"))
        text = "Strings rise over a steady kit. They ring out at the end. Fits: Trailer, Film"
        self.assertEqual(self.engine.manual_description(track, text, "rC", "g"), [])
        self.assertEqual((track["Track Description"], track["PFD_Status"]), (text, gate.PASSED))
        self.assertTrue(track["PFD_Manual"])
        self.assertEqual(len(gate.split_keywords(track["Keywords"])), 14)  # keywords from Call B

    def test_skip(self):
        self.replies(analysis_dict(), writing_dict())
        track = self.process()
        self.engine.skip(track)
        self.engine.refresh_status(track, "rC")
        self.assertEqual(track["PFD_Status"], "SKIPPED")


class TestConfigs(unittest.TestCase):
    def test_spec_configs(self):
        self.assertIs(CALL_A_CONFIG.response_schema, Analysis)
        self.assertEqual(CALL_A_CONFIG.response_mime_type, "application/json")
        self.assertIs(CALL_B_CONFIG.response_schema, Writing)
        self.assertEqual(list(Analysis.model_fields)[0], "analysis_scratchpad")


if __name__ == "__main__":
    unittest.main(verbosity=2)
