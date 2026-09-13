"""
Tests for capture.py: the export CSV/ZIP, the automatic DRAFT write, and the
DRAFT-vs-FINAL diff. Dropbox is a MagicMock; no network, no keys.
"""
import io
import re
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

import capture
import gate

ROOT = Path(__file__).resolve().parent


def _app_data(status=gate.PASSED):
    return {
        "catalog": "EPP",
        "album_name_selected": "Glass Hours",
        "album_description": "Slow brass and tape hiss for patient reveals.",
        "cover_art": "prompt one\n\nprompt two",
        "mailchimp_intro": "We made this for the long cut.",
        "album_name_candidates": ["Glass Hours", "Tin Weather"],
        "tracks": [{
            "Title": "Glass Hours Full Mix", "Mix Type": "full",
            "Track Description": "Brass swells over tape hiss. Ends on a button. Fits: Sounds Tender, Documentary",
            "Keywords": "Sounds Tender, Slow Brass", "PFD_Status": status,
            "PFD_Block_Reasons": [] if status == gate.PASSED else ["duration mismatch"],
        }],
    }


class TestExport(unittest.TestCase):
    def test_draft_written_on_export(self):
        dbx = MagicMock()
        zip_bytes, zip_name, draft_path = capture.export_album(dbx, _app_data(gate.BLOCKED), "EPP", "TEST")
        self.assertEqual(draft_path, "/PFD-App/albums/TEST/EPP_TEST_Glass_Hours_DRAFT.csv")
        dbx.files_upload.assert_called_once()
        data, path = dbx.files_upload.call_args.args[:2]
        self.assertEqual(path, draft_path)
        df = pd.read_csv(io.BytesIO(data))
        self.assertEqual(list(df.columns[-2:]), ["PFD_Status", "PFD_Block_Reasons"])
        self.assertEqual(df.loc[0, "PFD_Status"], "BLOCKED")
        self.assertIn("duration mismatch", df.loc[0, "PFD_Block_Reasons"])
        self.assertEqual(zip_name, "EPP_TEST_Glass_Hours.zip")

    def test_zip_is_one_csv_plus_text_assets(self):
        zip_bytes, _ = capture.build_zip(_app_data(), "EPP", "EPP062")
        names = zipfile.ZipFile(io.BytesIO(zip_bytes)).namelist()
        self.assertEqual(sum(n.endswith(".csv") for n in names), 1)
        self.assertEqual(sorted(n for n in names if n.endswith(".txt")),
                         ["Album_Description.txt", "Album_Names.txt", "Cover_Art_Prompts.txt", "MailChimp_Intro.txt"])
        self.assertFalse(any("/" in n for n in names), "no folders in the package")

    def test_track_without_status_exports_as_blocked(self):
        data = _app_data()
        data["tracks"][0].pop("PFD_Status")
        df = capture.track_rows(data, "EPP")
        self.assertEqual(df.loc[0, "PFD_Status"], "BLOCKED")

    def test_sourceaudio_column_reference_order(self):
        df = capture.track_rows(_app_data(), "EPP")
        ordered = capture.order_columns(df, ["Composer", "Title", "Keywords"])
        self.assertEqual(list(ordered.columns[:3]), ["Composer", "Title", "Keywords"])
        self.assertEqual(list(ordered.columns[-2:]), ["PFD_Status", "PFD_Block_Reasons"])
        self.assertEqual(capture.parse_columns_reference("A\nB\n\nC\n"), ["A", "B", "C"])
        self.assertEqual(capture.parse_columns_reference("A, B,C"), ["A", "B", "C"])

    def test_album_code_detection(self):
        self.assertEqual(capture.detect_album_code("/03 Ekonomic/EPP061 Body Works"), "EPP061")
        self.assertEqual(capture.detect_album_code("no code here"), "")


class TestDiff(unittest.TestCase):
    def test_word_edit_distance(self):
        self.assertEqual(capture.word_edit_distance("a b c", "a b c"), 0)
        self.assertEqual(capture.word_edit_distance("a b c", "a x c"), 1)
        self.assertEqual(capture.word_edit_distance("a b c", "a c"), 1)
        self.assertEqual(capture.word_edit_distance("", "a b"), 2)

    def test_diff_from_known_edits(self):
        draft = pd.DataFrame({
            "Title": ["One", "Two"],
            "Track Description": ["w1 w2 w3 w4 w5", "a b c d e"],
            "Keywords": ["K1, K2", "K3, K4"],
            "Album Description": ["one two three four", "one two three four"],
        })
        final = pd.DataFrame({  # Vesna's sheet: different column names and order
            "Track Title": ["Two", "One"],
            "Description": ["a b X d e", "w1 w2 w3 w4 w5"],
            "Tags": ["K3, K4", "K1, K9"],
            "Album_Description": ["one two five four", "one two five four"],
        })
        diff = capture.compute_diff(draft, final)
        self.assertEqual(diff["fields"]["track description"]["changed"], 1)
        self.assertEqual(diff["fields"]["track description"]["words"], 10)
        self.assertEqual(diff["fields"]["track description"]["pct"], 10.0)
        self.assertEqual(diff["fields"]["keywords"]["pct"], 25.0)
        self.assertEqual(diff["fields"]["album description"]["pct"], 25.0)
        md = capture.render_diff_md(diff, "EPP_TEST_Album")
        self.assertIn("Words changed — track description: 10.0% · keywords: 25.0% · album description: 25.0%", md)

    def test_final_upload_writes_final_and_diff(self):
        dbx = MagicMock()
        entry = MagicMock()
        entry.name = "EPP_TEST_Glass_Hours_DRAFT.csv"
        entry.path_display = "/PFD-App/albums/TEST/EPP_TEST_Glass_Hours_DRAFT.csv"
        dbx.files_list_folder.return_value.entries = [entry]
        draft_csv = capture.build_csv(_app_data(), "EPP")
        dbx.files_download.return_value = (MagicMock(), MagicMock(content=draft_csv))
        final = pd.read_csv(io.BytesIO(draft_csv))
        final.loc[0, "Track Description"] = "Brass swells over hiss. Ends on a button. Fits: Sounds Tender, Documentary"
        out = capture.save_final_and_diff(dbx, "TEST", final.to_csv(index=False).encode())
        paths = [c.args[1] for c in dbx.files_upload.call_args_list]
        self.assertEqual(paths, ["/PFD-App/albums/TEST/EPP_TEST_Glass_Hours_FINAL.csv",
                                 "/PFD-App/albums/TEST/EPP_TEST_Glass_Hours_DIFF.md"])
        self.assertIn("track description:", out["summary"])

    def test_final_without_draft_is_an_error(self):
        dbx = MagicMock()
        dbx.files_list_folder.return_value.entries = []
        with self.assertRaises(FileNotFoundError):
            capture.save_final_and_diff(dbx, "TEST", b"Title\nx\n")


class TestNoDrive(unittest.TestCase):
    DRIVE = re.compile(r"googleapiclient|google\.oauth2|google_auth_oauthlib|drive\.google\.com|"
                       r"build\(\s*['\"]drive['\"]|mcp__claude_ai_Google_Drive", re.IGNORECASE)

    def test_no_drive_calls_anywhere(self):
        for path in ROOT.glob("*.py"):
            if path.name.startswith("test_"):
                continue
            hits = self.DRIVE.findall(path.read_text(encoding="utf-8"))
            self.assertEqual(hits, [], f"{path.name} references Google Drive: {hits}")

    def test_no_drive_client_libraries_installed(self):
        reqs = (ROOT / "requirements.txt").read_text().lower()
        for lib in ("google-api-python-client", "google-auth-oauthlib"):
            self.assertNotIn(lib, reqs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
