"""
No silent failure on the analysis, generation, export and logging paths.
v2 had 11 `except Exception: pass` sites; a failed step looked like an empty result.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FILES = ("engine.py", "app.py", "persistence.py", "feedback.py")
SILENT = re.compile(r"except(\s+Exception)?\s*:\s*pass\b")


class TestNoSilentExcept(unittest.TestCase):
    def test_zero_silent_excepts(self):
        for name in FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            hits = [text[:m.start()].count("\n") + 1 for m in SILENT.finditer(text)]
            self.assertEqual(hits, [], f"{name}: silent except at lines {hits}")

    def test_the_pattern_catches_both_forms(self):
        self.assertTrue(SILENT.search("try:\n    x()\nexcept Exception:\n    pass\n"))
        self.assertTrue(SILENT.search("try: x()\nexcept: pass"))
        self.assertFalse(SILENT.search("except Exception as exc:\n    report('x', exc)"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
