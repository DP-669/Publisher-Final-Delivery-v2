"""
Revision capture: when an editor changes generated copy, both versions are kept.

Capture only — nothing reads these yet. They are the raw material for style
learning (DECISIONS.md → "Next RSI layer"). Gemini is mocked; no network.
"""
import json
import unittest

import engine
from pfd_fixtures import DESCRIPTION, KEYWORDS, analysis_dict, writing_dict
from test_listen import AUDIO, ListenCase


class TestRevisionCapture(ListenCase):
    def written_track(self, catalog="rC"):
        self.replies(analysis_dict(), writing_dict())
        return self.engine.process_track("Glass Hours", "full", AUDIO, ".mp3", catalog, "g", "",
                                         source_path="/rC057/glass hours.mp3")

    def test_the_generated_copy_is_pinned_when_it_is_written(self):
        track = self.written_track()
        self.assertEqual(engine.generated_text(track, "Track Description"), DESCRIPTION)
        self.assertEqual(engine.generated_text(track, "Keywords"), ", ".join(KEYWORDS))

    def test_an_edit_keeps_both_versions_with_the_catalog_and_the_track(self):
        track = self.written_track("SSC")
        edited = "Bowed strings hold one line. They fade under dialogue. Fits: Film, Drama"
        entry = engine.record_revision(track, "Track Description", track["Track Description"], edited,
                                       "SSC", "SSC042")
        self.assertEqual(entry["action"], "edit")
        self.assertEqual(entry["generated"], DESCRIPTION)     # what the app wrote
        self.assertEqual(entry["from"], DESCRIPTION)
        self.assertEqual(entry["to"], edited)                 # what the human wrote
        self.assertEqual(entry["catalog"], "SSC")
        self.assertEqual(entry["album_code"], "SSC042")
        self.assertEqual((entry["track"], entry["mix_type"]), ("Glass Hours", "full"))
        self.assertEqual(entry["track_id"], engine.track_key(track))
        self.assertTrue(entry["at"])
        self.assertTrue(entry["writer"])

    def test_the_generated_copy_survives_several_edits(self):
        track = self.written_track()
        first, second = "First human go. It ends hard. Fits: Trailer, Film", "Second go. It ends hard. Fits: Trailer, Film"
        engine.record_revision(track, "Track Description", track["Track Description"], first, "rC")
        track["Track Description"] = first
        engine.record_revision(track, "Track Description", first, second, "rC")
        track["Track Description"] = second
        self.assertEqual(engine.generated_text(track, "Track Description"), DESCRIPTION)
        log = engine.revisions(track)
        self.assertEqual([e["from"] for e in log], [DESCRIPTION, first])
        self.assertEqual([e["to"] for e in log], [first, second])
        self.assertTrue(all(e["generated"] == DESCRIPTION for e in log))

    def test_keywords_are_captured_too(self):
        track = self.written_track()
        entry = engine.record_revision(track, "Keywords", track["Keywords"], "Tone Alpha, Tone Bravo", "rC")
        self.assertEqual(entry["field"], "Keywords")
        self.assertEqual(entry["generated"], ", ".join(KEYWORDS))

    def test_writing_it_by_hand_is_captured(self):
        track = self.written_track()
        text = "Strings rise over a steady kit. They ring out at the end. Fits: Trailer, Film"
        self.replies(writing_dict())
        self.assertEqual(self.engine.manual_description(track, text, "rC", "g", album_code="RC057"), [])
        entry = engine.revisions(track)[-1]
        self.assertEqual((entry["action"], entry["to"], entry["album_code"]), ("manual", text, "RC057"))
        self.assertEqual(entry["generated"], DESCRIPTION)

    def test_the_log_survives_state_json(self):
        track = self.written_track()
        engine.record_revision(track, "Track Description", DESCRIPTION, "Edited. It ends. Fits: Trailer, Film", "rC")
        restored = json.loads(json.dumps(track, default=str))
        self.assertEqual(engine.revisions(restored)[0]["generated"], DESCRIPTION)

    def test_an_override_and_an_edit_share_one_log(self):
        track = self.written_track()
        self.engine.override_track(track, "rC", "g", "", "signed off by Damir")
        engine.record_revision(track, "Track Description", DESCRIPTION, "Edited. It ends. Fits: Trailer, Film", "rC")
        self.assertEqual([e["action"] for e in track["PFD_Log"]], ["override", "edit"])
        self.assertEqual(len(engine.revisions(track)), 1)     # the override is not a revision


if __name__ == "__main__":
    unittest.main(verbosity=2)
