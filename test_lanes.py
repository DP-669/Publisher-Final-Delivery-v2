"""
EPP lanes: the lane is the first keyword and first Fits tag on every track, and
never part of the album title. Claude is mocked; no keys, no network.
"""
import json
import unittest
from unittest.mock import patch

import gate
import rules
from engine import ClaudeError, IngestionEngine

NAMES = ["Trouble Maker", "Glass Hours", "Tin Weather", "Sounds Good", "Salt Road",
         "Paper Moon", "Orchestral Ghosts", "Copper Wire"]


def names_reply(names):
    return json.dumps({"names": [{"name": n, "rationale": "x"} for n in names]})


class TestNameCandidates(unittest.TestCase):
    @patch.object(IngestionEngine, "call_claude")
    def test_epp_name_with_a_lane_word_is_rejected(self, mock_claude):
        mock_claude.return_value = names_reply(NAMES)
        out = IngestionEngine().generate_album_names("Brass and tape.", "EPP", "k")
        accepted = [n["name"] for n in out["names"]]
        rejected = {r["name"]: r["reasons"] for r in out["rejected"]}
        for bad in ("Trouble Maker", "Sounds Good", "Orchestral Ghosts"):
            self.assertNotIn(bad, accepted)
            self.assertTrue(any("lane word" in r for r in rejected[bad]), rejected[bad])
        self.assertEqual(accepted, ["Glass Hours", "Tin Weather", "Salt Road", "Paper Moon", "Copper Wire"])

    @patch.object(IngestionEngine, "call_claude")
    def test_short_list_asks_again_for_the_missing_names(self, mock_claude):
        mock_claude.side_effect = [names_reply(["Trouble Maker", "Glass Hours", "Sounds Fine"]),
                                   names_reply(["Tin Weather", "Salt Road", "Paper Moon", "Copper Wire"])]
        out = IngestionEngine().generate_album_names("Brass and tape.", "EPP", "k")
        self.assertEqual(len(out["names"]), 5)
        self.assertIn("Trouble Maker", mock_claude.call_args_list[1].args[1])  # told what was rejected

    @patch.object(IngestionEngine, "call_claude")
    def test_lane_words_are_legal_outside_epp(self, mock_claude):
        mock_claude.return_value = names_reply(["Trouble Maker", "Glass Hours"])
        out = IngestionEngine().generate_album_names("x", "rC", "k")
        self.assertIn("Trouble Maker", [n["name"] for n in out["names"]])

    def test_name_rules(self):
        self.assertTrue(gate.album_name_reasons("Sounds Like Trouble", "EPP"))
        self.assertTrue(gate.album_name_reasons("Glass Hours: Vol. 2", "EPP"))
        self.assertTrue(gate.album_name_reasons("Four Words Are Here", "rC"))
        self.assertEqual(gate.album_name_reasons("Glass Hours", "EPP"), [])


class TestApplyLane(unittest.TestCase):
    def _data(self):
        kws = ", ".join(["Sounds Carefree"] + [f"Tone {i}" for i in range(17)])
        return {"catalog": "EPP", "tracks": [{
            "Title": "Glass Hours", "Mix Type": "full", "Keywords": kws,
            "Track Description": "Brass swells over tape hiss. It ends on a button. Fits: Sounds Carefree, Documentary, Lifestyle",
        }]}

    def test_lane_is_first_keyword_and_first_fits_tag(self):
        data = self._data()
        IngestionEngine().apply_lane(data, "Sounds Tender")
        track = data["tracks"][0]
        kws = gate.split_keywords(track["Keywords"])
        self.assertEqual(kws[0], "Sounds Tender")
        self.assertNotIn("Sounds Carefree", kws)  # a different lane never rides along
        self.assertLessEqual(len(kws), gate.KEYWORD_MAX)
        _, tags = gate.split_fits(track["Track Description"])
        self.assertEqual(tags, ["Sounds Tender", "Documentary", "Lifestyle"])
        self.assertEqual(data["lane"], "Sounds Tender")
        self.assertEqual(gate.keyword_reasons(track["Keywords"], "EPP", "Sounds Tender"), [])
        self.assertEqual(gate.fits_reasons(tags, "EPP", "Sounds Tender"), [])

    def test_fits_without_the_lane_first_fails(self):
        reasons = gate.fits_reasons(["Documentary", "Sounds Tender"], "EPP", "Sounds Tender")
        self.assertTrue(any(r["rule"] == "FITS_LANE" for r in reasons), reasons)
        self.assertTrue(gate.keyword_reasons("Documentary Cut, Sounds Tender", "EPP", "Sounds Tender"))

    def test_unknown_lane_is_refused(self):
        with self.assertRaises(ValueError):
            IngestionEngine().apply_lane(self._data(), "Sounds Like Nothing")

    @patch.object(IngestionEngine, "call_claude")
    def test_lane_proposal_must_be_a_real_lane(self, mock_claude):
        tracks = [{"analysis": {"job": "sneaky", "facts": {}, "keywords": [], "ending_type": "Button"}}]
        mock_claude.return_value = "sounds like mischief."
        self.assertEqual(IngestionEngine().propose_lane(tracks, "k"), "Sounds Like Mischief")
        mock_claude.return_value = "Sounds Like Pirates"
        with self.assertRaises(ClaudeError):
            IngestionEngine().propose_lane(tracks, "k")

    def test_active_lanes_listed_first(self):
        names = rules.lane_names()
        active = [l["name"] for l in rules.lanes() if l["status"] == "active"]
        self.assertEqual(names[:len(active)], active)


if __name__ == "__main__":
    unittest.main(verbosity=2)
