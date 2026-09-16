"""
Error states: a user sees what failed and what to do, never a bare traceback.
No network, no Streamlit runtime.
"""
import unittest

import pfd_errors


class TestExplain(unittest.TestCase):
    def test_quota(self):
        said = pfd_errors.explain("Analysis failed — Loaded Gun",
                                  RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded"))
        self.assertIn("run out of credit", said["what"])
        self.assertIn("Top up the Gemini credits", said["action"])

    def test_refused_key(self):
        said = pfd_errors.explain("Listening failed", RuntimeError("401 API key not valid"))
        self.assertIn("refused our key", said["what"])
        self.assertIn("Craig", said["action"])

    def test_dead_dropbox_link(self):
        said = pfd_errors.explain("Could not read that Dropbox link",
                                  RuntimeError("shared_link_not_found"))
        self.assertIn("doesn't open anything", said["what"])
        self.assertIn("paste it again", said["action"])

    def test_undecodable_audio(self):
        said = pfd_errors.explain("Could not decode the audio file", RuntimeError("could not decode"))
        self.assertIn("couldn't be opened", said["what"])
        self.assertIn("music player", said["action"])

    def test_anything_else_still_says_what_to_do(self):
        said = pfd_errors.explain("Writing failed — Glass Hours", TypeError("NoneType is not subscriptable"))
        self.assertTrue(said["what"].startswith("Writing failed — Glass Hours"))
        self.assertIn("Try it again", said["action"])

    def test_the_raw_exception_stays_out_of_the_message(self):
        exc = TypeError("argument of type 'NoneType' is not iterable")
        said = pfd_errors.explain("Analysis failed — Loaded Gun", exc)
        self.assertNotIn("TypeError", said["what"] + said["action"])
        self.assertIn("TypeError", said["detail"])      # kept, but folded away

    def test_report_without_streamlit_still_returns_the_log_line(self):
        msg = pfd_errors.report("Analysis failed — Loaded Gun", RuntimeError("boom"), show=False)
        self.assertEqual(msg, "Analysis failed — Loaded Gun: RuntimeError: boom")


if __name__ == "__main__":
    unittest.main(verbosity=2)
