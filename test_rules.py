"""
Tests for rules.py — PFD_RULES.md is the only rule source, so its parsing is
load-bearing: a broken parse means the model gets the wrong rules or none.
Reads the real PFD_RULES.md / EPP_LANES.md; no network.
"""
import re
import unittest

import gate
import rules
from rules import Rules, RulesError


class TestSections(unittest.TestCase):
    def test_version_line(self):
        raw = rules.RULES_PATH.read_text(encoding="utf-8")
        self.assertEqual(rules.version(), re.search(r"^version:\s*([0-9.]+)", raw, re.M).group(1))

    def test_locked_parses(self):
        self.assertIn("### Mission", rules.RULES.locked)
        self.assertIn("Hard banned list", rules.RULES.locked)
        self.assertNotIn("## CATALOG DNA", rules.RULES.locked)

    def test_all_three_catalog_blocks_parse(self):
        for code in ("rC", "SSC", "EPP"):
            block = rules.RULES.catalog_blocks[code]
            self.assertTrue(block.startswith(f"### {code}"))
            self.assertIn("Placement list for Fits:", block)

    def test_other_catalogs_absent_from_rc_instruction(self):
        si = rules.system_instruction("rC")
        self.assertIn(rules.RULES.catalog_blocks["rC"], si)
        self.assertIn(rules.RULES.locked, si)
        for other in ("SSC", "EPP"):
            block = rules.RULES.catalog_blocks[other]
            self.assertNotIn(block, si)
            for line in block.splitlines()[1:]:
                if line.strip():
                    self.assertNotIn(line.strip(), si, f"{other} line leaked: {line}")
        self.assertNotIn("Ekonomic Propaganda", si)
        self.assertNotIn("Short Story Collective", si)

    def test_epp_instruction_carries_lanes_and_no_other_blocks(self):
        si = rules.system_instruction("EPP")
        self.assertIn("Sounds Like Trouble", si)
        self.assertNotIn(rules.RULES.catalog_blocks["rC"], si)
        self.assertNotIn(rules.RULES.catalog_blocks["SSC"], si)

    def test_catalog_name_variants(self):
        for name, code in (("redCola", "rC"), ("rc", "rC"), ("Short Story Collective", "SSC"),
                           ("ssc", "SSC"), ("Ekonomic Propaganda", "EPP")):
            self.assertEqual(rules.catalog_code(name), code)
        with self.assertRaises(RulesError):
            rules.catalog_code("Mystery Label")

    def test_missing_section_is_an_error(self):
        with self.assertRaises(RulesError):
            Rules("version: 1\n## LOCKED\nx\n## TUNABLE\ny\n")


class TestSettings(unittest.TestCase):
    def test_track_writer_reads_the_file(self):
        raw = rules.RULES_PATH.read_text(encoding="utf-8")
        section = raw.split("### track_writer", 1)[1]
        expected = re.search(r"`([^`]+)`", section).group(1)
        self.assertEqual(rules.setting("track_writer"), expected)

    def test_track_writer_follows_an_edit(self):
        raw = rules.RULES_PATH.read_text(encoding="utf-8")
        edited = re.sub(r"(### track_writer\n)`[^`]+`", r"\1`claude_edit`", raw)
        self.assertEqual(Rules(edited).setting("track_writer"), "claude_edit")

    def test_tunable_sections_used_by_templates_exist(self):
        for name in ("Analysis schema", "Track description", "Keywords", "Album description",
                     "Album names", "MailChimp intro", "Cover-art prompts"):
            self.assertTrue(rules.tunable(name))


class TestParsedLists(unittest.TestCase):
    def test_banned_list_matches_the_locked_line(self):
        raw = rules.RULES_PATH.read_text(encoding="utf-8")
        line = raw.split("### Hard banned list", 1)[1].split("\n", 2)[1]
        expected = [w.strip().rstrip(".").lower() for w in line.rstrip(".").split(",")]
        self.assertEqual(rules.banned_list(), expected)
        self.assertIn("sonic short stories", rules.banned_list())

    def test_banned_list_follows_an_edit(self):
        raw = rules.RULES_PATH.read_text(encoding="utf-8")
        edited = raw.replace("sonic short stories.", "sonic short stories, gritty.")
        self.assertIn("gritty", Rules(edited).banned_list())

    def test_forbidden_placement_words_parse(self):
        rc = [f["word"] for f in rules.forbidden_placement_words("rC")]
        self.assertIn("advertising", rc)
        self.assertIn("esports", rc)
        epp = [f["word"] for f in rules.forbidden_placement_words("EPP")]
        self.assertIn("trailer", epp)
        self.assertIn("hollywood", epp)
        ssc = {f["word"]: f["qualifier"] for f in rules.forbidden_placement_words("SSC")}
        self.assertEqual(ssc["trailer"], "as a lead placement")
        self.assertIn("underscore", ssc)  # SSC forbidden jargon

    def test_fits_lists_parse(self):
        self.assertEqual(rules.fits_list("rC")[0], "Trailer")
        self.assertIn("Prestige TV", rules.fits_list("SSC"))
        epp = rules.fits_list("EPP")
        self.assertIn("Reality TV", epp)
        self.assertFalse(any("lane" in t.lower() for t in epp))

    def test_lanes_active_first(self):
        lanes = rules.lanes()
        statuses = [l["status"] for l in lanes]
        self.assertEqual(statuses, sorted(statuses))  # "active" < "dormant"
        self.assertEqual(lanes[0]["name"], "Sounds Like Trouble")
        self.assertIn("trouble", rules.lane_words())
        self.assertNotIn("like", rules.lane_words())

    def test_few_shot_is_catalog_scoped(self):
        rc, epp = rules.few_shot("rC", "Track"), rules.few_shot("EPP", "Track")
        self.assertTrue(rc and epp)
        self.assertFalse(set(rc) & set(epp))
        for text in rc + rules.few_shot("rC", "Album") + epp:
            self.assertEqual(gate.banned_found(text), [], text)
        import prompts
        prompt = prompts.PromptEngine().analysis_prompt("full", "rC")
        self.assertIn(rc[0], prompt)
        self.assertNotIn(epp[0], prompt)

    def test_analysis_schema_matches_the_rules_block(self):
        keys = [k for k in gate.analysis_schema()["property_ordering"] if k != "description"]
        self.assertEqual(keys, rules.RULES.analysis_schema_keys())


if __name__ == "__main__":
    unittest.main(verbosity=2)
