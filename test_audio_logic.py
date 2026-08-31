import unittest
from unittest.mock import MagicMock, patch
import json
from engine import IngestionEngine

class TestAudioAnalysis(unittest.TestCase):
    
    @patch('engine.genai')
    def test_analyze_audio_file_success(self, mock_genai):
        # Setup Mock
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        mock_file = MagicMock()
        mock_file.state.name = "ACTIVE"
        mock_file.name = "remote_file_id"
        mock_genai.upload_file.return_value = mock_file
        mock_genai.get_file.return_value = mock_file
        
        # Mock Response
        mock_response = MagicMock()
        mock_response.text = '```json\n{"Title": "Test Track", "Composer": "", "Keywords": "key1; key2", "Description": "Desc", "Best_Use": "Trailer"}\n```'
        mock_model.generate_content.return_value = mock_response
        
        # Execute
        engine = IngestionEngine()
        result = engine.analyze_audio_file("dummy.mp3", "redCola", "fake_key")
        
        # Verify
        self.assertIsNotNone(result)
        self.assertEqual(result['Title'], "Test Track")
        self.assertEqual(result['Keywords'], "Key1, Key2")
        
        # Check Calls
        mock_genai.configure.assert_called_with(api_key="fake_key")
        mock_genai.upload_file.assert_called_with(path="dummy.mp3")
        mock_model.generate_content.assert_called_once()
        mock_genai.delete_file.assert_called_with("remote_file_id")

    @patch('engine.genai')
    def test_analyze_audio_file_json_error(self, mock_genai):
        # Setup Mock
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        
        mock_file = MagicMock()
        mock_file.state.name = "ACTIVE"
        mock_genai.upload_file.return_value = mock_file
        
        # Mock Invalid JSON Response
        mock_response = MagicMock()
        mock_response.text = 'Invalid JSON output'
        mock_model.generate_content.return_value = mock_response
        
        # Execute
        engine = IngestionEngine()
        result = engine.analyze_audio_file("dummy.mp3", "redCola", "fake_key")
        
        # Verify
        self.assertIsNone(result)

if __name__ == '__main__':
    unittest.main()
