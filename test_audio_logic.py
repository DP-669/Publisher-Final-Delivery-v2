"""
Tests for IngestionEngine.analyze_audio_file — the response-parsing path.

This is the highest-risk step in the app: Gemini returns JSON, sometimes in a
markdown fence, and its keys arrive in several shapes. Everything downstream
(descriptions, CSV, delivery) is built on what this returns.

The Gemini client is mocked against the current google.genai surface
(genai.Client(...).models.generate_content), so no key and no network.
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from engine import IngestionEngine

GOOD = {
    "Overall_Consensus": "Slow burn to a hard cut.",
    "Trailer_Description": "Builds from sparse pulse to full brass.",
    "Editor_Description": "Cuts cleanly at 1:42.",
    "Supervisor_Description": "Leaves dialogue space throughout.",
    "Keywords": "dark thriller, chase scene, epic",
    "Tip": "Try the alt mix for the back half.",
}


class TestAnalyzeAudioFile(unittest.TestCase):
    def setUp(self):
        self.engine = IngestionEngine()
        fd, self.audio = tempfile.mkstemp(suffix=".mp3")
        os.write(fd, b"\x00\x01not-real-audio")
        os.close(fd)

    def tearDown(self):
        os.unlink(self.audio)

    def _run(self, mock_genai, reply_text, catalog="redCola"):
        mock_genai.Client.return_value.models.generate_content.return_value.text = reply_text
        return self.engine.analyze_audio_file(self.audio, "Test Track", catalog, "fake_key")

    @patch("engine.genai")
    def test_parses_a_markdown_fenced_response(self, mock_genai):
        result = self._run(mock_genai, "```json\n" + json.dumps(GOOD) + "\n```")
        self.assertEqual(result["Overall Consensus"], "Slow burn to a hard cut.")
        self.assertEqual(result["Tip"], "Try the alt mix for the back half.")

    @patch("engine.genai")
    def test_parses_a_bare_json_response(self, mock_genai):
        result = self._run(mock_genai, json.dumps(GOOD))
        self.assertEqual(result["Editor Description"], "Cuts cleanly at 1:42.")

    @patch("engine.genai")
    def test_underscore_keys_are_normalised_to_spaces(self, mock_genai):
        result = self._run(mock_genai, json.dumps(GOOD))
        for key in ("Overall Consensus", "Editor Description", "Supervisor Description"):
            self.assertIn(key, result)
        for key in ("Overall_Consensus", "Editor_Description", "Supervisor_Description"):
            self.assertNotIn(key, result)

    @patch("engine.genai")
    def test_trailer_description_for_a_trailer_catalog(self, mock_genai):
        result = self._run(mock_genai, json.dumps(GOOD), catalog="redCola")
        self.assertIn("Trailer Description", result)
        self.assertNotIn("Campaign Description", result)

    @patch("engine.genai")
    def test_campaign_description_for_epp(self, mock_genai):
        """EPP is production music, not trailer music — the label must follow."""
        result = self._run(mock_genai, json.dumps(GOOD), catalog="EPP")
        self.assertIn("Campaign Description", result)
        self.assertNotIn("Trailer Description", result)

    @patch("engine.genai")
    def test_keywords_go_through_the_ban_filter(self, mock_genai):
        result = self._run(mock_genai, json.dumps(GOOD))
        self.assertEqual(result["Keywords"], "Dark Thriller, Chase Scene")
        self.assertNotIn("epic", result["Keywords"].lower())

    @patch("engine.genai")
    def test_a_non_json_response_fails_loudly(self, mock_genai):
        """
        Current behaviour, and the behaviour we want: a garbled response raises
        rather than returning a half-empty dict. A silent empty row would be
        delivered as if it were real analysis.
        """
        with self.assertRaises(json.JSONDecodeError):
            self._run(mock_genai, "I'm sorry, I can't analyse that file.")

    @patch("engine.genai")
    def test_the_pinned_model_is_the_one_called(self, mock_genai):
        import engine as engine_mod
        self._run(mock_genai, json.dumps(GOOD))
        call = mock_genai.Client.return_value.models.generate_content.call_args_list[0]
        self.assertEqual(call.kwargs["model"], engine_mod.GEMINI_AUDIO_MODEL)

    @patch("engine.genai")
    def test_the_audio_is_actually_sent_as_bytes(self, mock_genai):
        """
        The whole point of this step is that the model hears the file. If the
        audio part ever stops being attached, the model will still return
        confident, entirely invented analysis.
        """
        self._run(mock_genai, json.dumps(GOOD))
        call = mock_genai.Client.return_value.models.generate_content.call_args_list[0]
        audio_part = call.kwargs["contents"][0]
        self.assertEqual(audio_part.inline_data.mime_type, "audio/mpeg")
        self.assertTrue(audio_part.inline_data.data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
