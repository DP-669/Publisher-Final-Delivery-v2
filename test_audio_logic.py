"""
Tests for the Gemini request/response path of engine.analyze_track.

v2's tests here covered a parser for free-form JSON keyed by the track title.
v3 replaced that contract (structured output, no title in the prompt, see
DECISIONS.md), so these keep the same intents against the new path: the audio
is really attached, the resolved model is the one called, garbage fails loudly,
and keywords still go through the ban filter.
"""
import json
import unittest
from unittest.mock import MagicMock, patch

import gate
from engine import IngestionEngine
from test_gate import analysis, verification


class TestAnalysisRequest(unittest.TestCase):
    def setUp(self):
        self.engine = IngestionEngine()
        p = patch("gate.read_duration", return_value=30.0)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, mock_genai, replies, mix="full"):
        client = mock_genai.Client.return_value
        client.models.generate_content.side_effect = [MagicMock(text=json.dumps(r)) for r in replies]
        return self.engine.analyze_track(b"\xff\xfbaudio-bytes", ".mp3", mix, "rC", "fake_key"), client

    @patch("engine.genai")
    def test_the_audio_is_actually_sent_as_bytes(self, mock_genai):
        """If the audio part stops being attached, the model still returns confident, invented analysis."""
        _, client = self._run(mock_genai, [analysis(), verification()])
        for call in client.models.generate_content.call_args_list:
            part = call.kwargs["contents"][0]
            self.assertEqual(part.inline_data.mime_type, "audio/mpeg")
            self.assertEqual(part.inline_data.data, b"\xff\xfbaudio-bytes")

    @patch("engine.genai")
    def test_the_resolved_model_is_the_one_called(self, mock_genai):
        self.engine.gemini_model = "gemini-9.9-pro"
        _, client = self._run(mock_genai, [analysis(), verification()])
        for call in client.models.generate_content.call_args_list:
            self.assertEqual(call.kwargs["model"], "gemini-9.9-pro")

    @patch("engine.genai")
    def test_mix_type_is_in_the_prompt(self, mock_genai):
        _, client = self._run(mock_genai, [analysis(mix_type="SPARSE"), verification()], mix="sparse")
        prompt = client.models.generate_content.call_args_list[0].kwargs["contents"][1]
        self.assertIn("SPARSE", prompt)

    @patch("engine.genai")
    def test_verification_is_a_stripped_claims_prompt(self, mock_genai):
        _, client = self._run(mock_genai, [analysis(), verification()])
        prompt = client.models.generate_content.call_args_list[1].kwargs["contents"][1]
        self.assertTrue(prompt.startswith("Here are claims about this audio. Answer each TRUE or FALSE."))
        self.assertIn("Drums are present.", prompt)
        self.assertNotIn("Rising pressure", prompt)  # the first listen's prose is not shown to the second

    @patch("engine.genai")
    def test_a_non_json_response_fails_loudly(self, mock_genai):
        client = mock_genai.Client.return_value
        client.models.generate_content.return_value.text = "I'm sorry, I can't analyse that file."
        with self.assertRaises(gate.SchemaViolation):
            self.engine.analyze_track(b"x", ".mp3", "full", "rC", "k")

    @patch("engine.genai")
    def test_keywords_go_through_the_ban_filter(self, mock_genai):
        kws = analysis()["keywords"][:-1] + ["Epic Rise"]
        result, _ = self._run(mock_genai, [analysis(keywords=kws), verification()])
        self.assertNotIn("Epic Rise", result["analysis"]["keywords"])
        self.assertIn("Epic Rise", result["analysis"]["keywords_raw"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
