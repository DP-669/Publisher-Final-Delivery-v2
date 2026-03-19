import unittest
from unittest.mock import MagicMock, patch
from engine import IngestionEngine
from pathlib import Path

class TestKeywordEngine(unittest.TestCase):

    def setUp(self):
        self.engine = IngestionEngine()
        
    @patch('engine.genai')
    def test_process_keywords_formatting(self, mock_genai):
        # Setup Mock
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        # We test regular formatting (Title Case, comma separated)
        # Note: No > 3 words phrases here, so LLM won't be called for correction
        raw_keywords = "dark thriller, intense action,   CHASE SCENE,epic, huge"
        # "epic" and "huge" should be filtered out by global ban.
        
        result = self.engine.process_keywords(raw_keywords, "redCola", "fake_key")
        
        expected = "Dark Thriller, Intense Action, Chase Scene"
        self.assertEqual(result, expected)
        mock_model.generate_content.assert_not_called()

    @patch('engine.genai')
    def test_process_keywords_auto_correction(self, mock_genai):
        # Setup Mock
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        mock_response = MagicMock()
        mock_response.text = "End Of World"
        mock_model.generate_content.return_value = mock_response
        
        # "end of the world today" has 4 spaces (> 2 spaces)
        raw_keywords = "dark thriller, end of the world today"
        
        result = self.engine.process_keywords(raw_keywords, "redCola", "fake_key")
        
        # Expected: "Dark Thriller, End Of World" 
        expected = "Dark Thriller, End Of World"
        self.assertEqual(result, expected)
        mock_model.generate_content.assert_called_once()
        
    @patch('engine.genai')
    def test_process_keywords_catalog_ban(self, mock_genai):
        # Setup Mock
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        # Mocking the folder finding mechanism for Banned_Keywords
        mock_folder = MagicMock(spec=Path)
        mock_folder.exists.return_value = True
        
        mock_file = MagicMock(spec=Path)
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = "forbidden word\nanother ban\n"
        
        self.engine.folders["02_VOICE_GUIDES"] = mock_folder
        mock_folder.__truediv__.return_value = mock_file
        mock_folder.glob.return_value = []
        
        raw_keywords = "dark thriller, forbidden word, keep this"
        
        result = self.engine.process_keywords(raw_keywords, "redCola", "fake_key")
        
        expected = "Dark Thriller, Keep This"
        self.assertEqual(result, expected)

if __name__ == '__main__':
    unittest.main()
