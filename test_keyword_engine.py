"""
Tests for IngestionEngine.process_keywords.

This is delivery-critical: these keywords ship in the final CSV. If the ban
filter breaks, banned words reach the library and nobody sees it until a
client does.

Hermetic — the engine is pointed at a temp directory so the repo's real
02_VOICE_GUIDES/Banned_Keywords.txt cannot change the outcome, and the Gemini
client is mocked, so nothing here touches the network.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from engine import IngestionEngine


class KeywordTestCase(unittest.TestCase):
    def setUp(self):
        # An empty root: no 02_VOICE_GUIDES, so only the hardcoded ban list applies.
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = IngestionEngine(root_path=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _mock_reply(mock_genai, text):
        """Wire engine.genai so client.models.generate_content().text is `text`."""
        client = mock_genai.Client.return_value
        client.models.generate_content.return_value.text = text
        return client


class TestProcessKeywords(KeywordTestCase):
    @patch("engine.genai")
    def test_formats_and_drops_banned_words(self, mock_genai):
        client = self._mock_reply(mock_genai, "")
        result = self.engine.process_keywords(
            "dark thriller, intense action,   CHASE SCENE,epic, huge",
            "redCola", "fake_key",
        )
        self.assertEqual(result, "Dark Thriller, Intense Action, Chase Scene")
        # Nothing here is longer than three words, so no model call is needed.
        client.models.generate_content.assert_not_called()

    @patch("engine.genai")
    def test_long_phrase_is_sent_for_correction(self, mock_genai):
        client = self._mock_reply(mock_genai, "End Of World")
        result = self.engine.process_keywords(
            "dark thriller, end of the world today", "redCola", "fake_key",
        )
        self.assertEqual(result, "Dark Thriller, End Of World")
        client.models.generate_content.assert_called_once()

    @patch("engine.IngestionEngine._alert_keyword_warnings")
    @patch("engine.genai")
    def test_model_failure_keeps_the_phrase_whole(self, mock_genai, mock_alert):
        """
        When the shortener fails, the phrase ships intact. It must NOT be
        chopped to its first three words — that used to deliver "End Of The".
        """
        client = mock_genai.Client.return_value
        client.models.generate_content.side_effect = RuntimeError("API down")
        result = self.engine.process_keywords(
            "end of the world today", "redCola", "fake_key",
        )
        self.assertEqual(result, "End Of The World Today")

    @patch("engine.IngestionEngine._alert_keyword_warnings")
    @patch("engine.genai")
    def test_model_failure_is_recorded_for_review(self, mock_genai, mock_alert):
        """Nothing is lost, but a human has to be told it went out unreviewed."""
        client = mock_genai.Client.return_value
        client.models.generate_content.side_effect = RuntimeError("API down")
        self.engine.process_keywords("end of the world today", "redCola", "k")

        self.assertEqual(len(self.engine.keyword_warnings), 1)
        warning = self.engine.keyword_warnings[0]
        self.assertEqual(warning["keyword"], "end of the world today")
        self.assertIn("API down", warning["reason"])
        mock_alert.assert_called_once_with("redCola")

    @patch("engine.IngestionEngine._alert_keyword_warnings")
    @patch("engine.genai")
    def test_empty_shortener_reply_also_keeps_the_phrase_whole(self, mock_genai, mock_alert):
        self._mock_reply(mock_genai, "   ")
        result = self.engine.process_keywords("end of the world today", "SSC", "k")
        self.assertEqual(result, "End Of The World Today")
        self.assertEqual(len(self.engine.keyword_warnings), 1)

    @patch("engine.IngestionEngine._alert_keyword_warnings")
    @patch("engine.genai")
    def test_a_successful_shortening_raises_no_warning(self, mock_genai, mock_alert):
        self._mock_reply(mock_genai, "End Of World")
        self.engine.process_keywords("end of the world today", "SSC", "k")
        self.assertEqual(self.engine.keyword_warnings, [])
        mock_alert.assert_not_called()

    @patch("engine.IngestionEngine._alert_keyword_warnings")
    @patch("engine.genai")
    def test_warnings_reset_between_runs(self, mock_genai, mock_alert):
        """A stale warning from a previous track must not follow the next one."""
        client = mock_genai.Client.return_value
        client.models.generate_content.side_effect = RuntimeError("API down")
        self.engine.process_keywords("end of the world today", "SSC", "k")
        self.assertEqual(len(self.engine.keyword_warnings), 1)

        client.models.generate_content.side_effect = None
        client.models.generate_content.return_value.text = "End Of World"
        self.engine.process_keywords("end of the world today", "SSC", "k")
        self.assertEqual(self.engine.keyword_warnings, [])

    @patch("engine.genai")
    def test_an_over_long_shortener_reply_is_still_trimmed(self, mock_genai):
        """The shortener answering with another long phrase is not a failure."""
        self._mock_reply(mock_genai, "one two three four five")
        result = self.engine.process_keywords("end of the world today", "SSC", "k")
        self.assertEqual(result, "One Two Three")
        self.assertEqual(self.engine.keyword_warnings, [])

    @patch("engine.genai")
    def test_catalog_ban_file_is_applied(self, mock_genai):
        self._mock_reply(mock_genai, "")
        guides = Path(self._tmp.name) / "02_VOICE_GUIDES"
        guides.mkdir()
        (guides / "Banned_Keywords.txt").write_text(
            "forbidden word\nanother ban\n", encoding="utf-8"
        )
        self.engine.set_root_path(self._tmp.name)

        result = self.engine.process_keywords(
            "dark thriller, forbidden word, keep this", "redCola", "fake_key",
        )
        self.assertEqual(result, "Dark Thriller, Keep This")

    @patch("engine.genai")
    def test_empty_input(self, mock_genai):
        self.assertEqual(self.engine.process_keywords("", "redCola", "k"), "")

    @patch("engine.genai")
    def test_caps_at_twenty_keywords(self, mock_genai):
        self._mock_reply(mock_genai, "")
        raw = ", ".join(f"tag{i}" for i in range(30))
        self.assertEqual(len(self.engine.process_keywords(raw, "SSC", "k").split(", ")), 20)


if __name__ == "__main__":
    unittest.main(verbosity=2)
