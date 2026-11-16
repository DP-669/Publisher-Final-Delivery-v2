"""Card files in the catalog card shape (2026-11-16): same columns as the Nov 2026 cards CSV,
sound design elements get the short card, ids/parents follow the catalog."""
import csv, io, json, unittest
from unittest.mock import MagicMock

import capture
import cards

MUSIC = {"sa_description": "Dark pulses build to a wall.", "sa_keywords": ["Dark", "pulse", "dark", "build"],
         "what_it_is": "hybrid pulse", "emotion": "dread", "energy_arc": "sparse -> wall", "world": "horror",
         "best_for": ["stalking scene"], "not_for": ["comedy"], "instruments_heard": ["synth", "strings"],
         "search_text": "dark hybrid pulse", "vocals": "none"}
SFX = {"card_type": "sound_design", "element_type": "hit", "character": "metallic, cavernous",
       "envelope": "instant attack, 4 s tail", "tail": "long", "key_moment": "0:00", "sound_sources": ["metal", "sub"],
       "world": "horror", "best_for": ["title card slam"], "not_for": ["comedy"], "search_text": "metal hit",
       "sa_description": "A cavernous metal hit.", "sa_keywords": ["hit", "metal"]}


def tracks():
    return [
        {"Title": "Extinction", "Mix Type": "full", "PFD_Card": MUSIC, "Duration Seconds": 120.0},
        {"Title": "Extinction Sparse Mix", "Mix Type": "sparse", "Parent Track": "Extinction", "PFD_Card": MUSIC},
        {"Title": "Extinction Mechanical Hit 1", "Mix Type": "sound_design", "Parent Track": "Extinction", "PFD_Card": SFX},
        {"Title": "Skipped", "Mix Type": "full", "PFD_Skipped": True},
        {"Title": "No Card", "Mix Type": "full"},
    ]


class TestCardExports(unittest.TestCase):
    def test_columns_match_catalog_cards_csv(self):
        nov15 = ("id,catalog,version,parent,sourceaudio_id,title,album,duration,has_card,vocals,new_description,new_keywords,"
                 "what_it_is,emotion,energy_arc,world,orchestral_vs_electronic_0_10,sweeping_strings,percussion_only,best_for,"
                 "not_for,signature_sounds,instruments_heard,comparable_to,sections,search_text,old_sourceaudio_description,"
                 "old_sourceaudio_tags,genre,mood,bpm,source_file").split(",")
        self.assertEqual(cards.CARD_CSV_COLUMNS[:len(nov15)], nov15)

    def test_rows_ids_parents_and_sound_design(self):
        rows, sa, recs = cards.card_exports(tracks(), "rC", "Album ONE", "RC070")
        self.assertEqual([r["id"] for r in rows], ["rc070-001", "rc070-002", "rc070-003", "rc070-004"])
        self.assertEqual([r["version"] for r in rows], ["full", "sparse", "sound_design", "full"])
        self.assertEqual(rows[1]["parent"], "rc070-001")
        self.assertEqual(rows[2]["parent"], "rc070-001")
        self.assertEqual(rows[0]["new_keywords"], "dark, pulse, build")
        self.assertEqual(rows[2]["element_type"], "hit")
        self.assertEqual(rows[2]["energy_arc"], "instant attack, 4 s tail")
        self.assertEqual(rows[2]["instruments_heard"], "metal; sub")
        self.assertEqual(rows[3]["has_card"], "no")
        self.assertEqual(len(recs), 3)                      # no record without a card
        self.assertIn("Type: hit", recs[2]["card"])
        self.assertEqual(recs[1]["parent"], "rc070-001")
        self.assertEqual(sa[2]["New Description"], "A cavernous metal hit.")

    def test_no_album_code_yet(self):
        rows, _, _ = cards.card_exports(tracks()[:1], "rC", "Album ONE", "")
        self.assertEqual(rows[0]["id"], "new-001")

    def test_files_build(self):
        full, sa, recs = capture.build_card_files({"tracks": tracks(), "album_name_selected": "Album ONE"}, "rC", "RC070")
        header = next(csv.reader(io.StringIO(full.decode("utf-8-sig"))))
        self.assertEqual(header, cards.CARD_CSV_COLUMNS)
        self.assertEqual(len(json.loads(recs)), 3)


class TestSoundDesignCard(unittest.TestCase):
    def test_is_sound_design(self):
        for m in ("sound_design", "Sound Design", "sde"):
            self.assertTrue(cards.is_sound_design(m))
        self.assertFalse(cards.is_sound_design("full"))

    def test_make_sfx_card_marks_type(self):
        client = MagicMock()
        client.models.generate_content.return_value.text = json.dumps({"element_type": "rise", "sa_keywords": ["rise"]})
        eng = MagicMock(gemini_model="m")
        out = cards.make_sfx_card(eng, client, "audio", "Riser 1", 6.0)
        self.assertEqual(out["card"]["card_type"], "sound_design")
        self.assertEqual(out["card"]["element_type"], "rise")

    def test_make_sfx_card_failure_never_blocks(self):
        client = MagicMock()
        client.models.generate_content.side_effect = RuntimeError("boom")
        out = cards.make_sfx_card(MagicMock(gemini_model="m"), client, "audio", "Riser 1", 6.0)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
