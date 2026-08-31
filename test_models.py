"""
Offline tests for models.py — version parsing and supersede logic.
No API keys and no network: these test the comparison rules only.
"""
import unittest
import models


class TestGeminiParsing(unittest.TestCase):
    def test_parses_versioned_pro(self):
        p = models.gemini_parts("gemini-3.1-pro-preview")
        self.assertEqual(p["version"], (3, 1))
        self.assertEqual(p["family"], "pro")
        self.assertTrue(p["preview"])

    def test_parses_stable_flash(self):
        p = models.gemini_parts("gemini-3.6-flash")
        self.assertEqual(p["version"], (3, 6))
        self.assertEqual(p["family"], "flash")
        self.assertFalse(p["preview"])

    def test_strips_models_prefix(self):
        self.assertEqual(models.gemini_parts("models/gemini-2.5-pro")["version"], (2, 5))

    def test_flash_lite_is_its_own_family(self):
        self.assertEqual(models.gemini_parts("gemini-3.6-flash-lite")["family"], "flash-lite")

    def test_rejects_non_chat_models(self):
        for mid in ("text-embedding-004", "imagen-4.0-generate", "veo-3.0",
                    "gemini-embedding-001", "gemma-3-27b"):
            self.assertIsNone(models.gemini_parts(mid), mid)


class TestClaudeParsing(unittest.TestCase):
    def test_new_scheme(self):
        p = models.claude_parts("claude-sonnet-5")
        self.assertEqual((p["tier"], p["version"]), ("sonnet", (5, 0)))

    def test_new_scheme_with_minor_and_datestamp(self):
        p = models.claude_parts("claude-opus-4-1-20250805")
        self.assertEqual((p["tier"], p["version"]), ("opus", (4, 1)))

    def test_old_scheme(self):
        p = models.claude_parts("claude-3-5-sonnet-20241022")
        self.assertEqual((p["tier"], p["version"]), ("sonnet", (3, 5)))

    def test_datestamp_is_not_a_minor_version(self):
        p = models.claude_parts("claude-haiku-4-5-20251001")
        self.assertEqual(p["version"], (4, 5))

    def test_rejects_unknown(self):
        self.assertIsNone(models.claude_parts("gpt-4o"))


class TestComparison(unittest.TestCase):
    def _gem(self, pinned, available):
        return models._compare(pinned, available, models.gemini_parts, "family")

    def test_flags_newer_in_same_family(self):
        r = self._gem("gemini-3.1-pro-preview",
                      ["gemini-3.1-pro-preview", "gemini-3.4-pro", "gemini-3.6-flash"])
        self.assertEqual([c["id"] for c in r["newer"]], ["gemini-3.4-pro"])

    def test_other_family_is_not_an_upgrade(self):
        # A newer Flash does not supersede the Pro the app runs audio on.
        r = self._gem("gemini-3.1-pro-preview", ["gemini-3.1-pro-preview", "gemini-3.6-flash"])
        self.assertEqual(r["newer"], [])

    def test_stable_build_of_pinned_preview_is_surfaced(self):
        r = self._gem("gemini-3.1-pro-preview", ["gemini-3.1-pro-preview", "gemini-3.1-pro"])
        self.assertEqual(r["stable_of_pinned"], "gemini-3.1-pro")
        self.assertEqual(r["newer"], [])

    def test_pinned_missing_from_provider_list(self):
        r = self._gem("gemini-3.1-pro-preview", ["gemini-3.4-pro"])
        self.assertFalse(r["pinned_available"])

    def test_pinned_present(self):
        r = self._gem("gemini-3.1-pro-preview", ["models/gemini-3.1-pro-preview"])
        self.assertTrue(r["pinned_available"])

    def test_claude_tier_is_respected(self):
        r = models._compare("claude-sonnet-5",
                            ["claude-sonnet-5", "claude-opus-6", "claude-sonnet-6"],
                            models.claude_parts, "tier")
        self.assertEqual([c["id"] for c in r["newer"]], ["claude-sonnet-6"])

    def test_summarize_reports_up_to_date(self):
        r = self._gem("gemini-3.1-pro", ["gemini-3.1-pro"])
        self.assertIn("newest in its family", models.summarize(r, "Gemini"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
