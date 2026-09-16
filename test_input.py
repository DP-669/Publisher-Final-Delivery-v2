"""
Input shapes: a single Dropbox file, a folder of loose files, and the mix type
read from a file name. v4 briefly accepted only album folders; Damir's team
needs all of it back. Dropbox is a MagicMock; no network.
"""
import unittest
from unittest.mock import MagicMock

import dropbox

import dropbox_pipeline as dp


def file_meta(name, path=None, size=3_000_000, file_id="id:1"):
    meta = MagicMock(spec=dropbox.files.FileMetadata)
    meta.name = name
    meta.path_lower = (path or f"/album/{name}").lower()
    meta.path_display = path or f"/album/{name}"
    meta.size = size
    meta.id = file_id
    return meta


def folder_meta(name):
    meta = MagicMock(spec=dropbox.files.FolderMetadata)
    meta.name = name
    meta.path_lower = f"/album/{name}".lower()
    return meta


class TestMixTypeFromName(unittest.TestCase):
    def test_full_is_the_default(self):
        for name in ("Glass Hours.mp3", "Glass Hours Full Mix.wav", "01 Loaded Gun master.mp3"):
            self.assertEqual(dp.detect_mix_type(name), "full", name)

    def test_sparse_and_sound_design(self):
        for name in ("Glass Hours Sparse Mix.mp3", "glass hours sparce.wav", "Tin Weather SP_2.mp3"):
            self.assertEqual(dp.detect_mix_type(name), "sparse", name)
        for name in ("Riser SDE.wav", "Glass Hours Sound Design.mp3", "Metal Element 3.aif"):
            self.assertEqual(dp.detect_mix_type(name), "sound_design", name)


class TestSingleFile(unittest.TestCase):
    def test_one_file_becomes_one_analysable_entry(self):
        dbx = MagicMock()
        dbx.files_get_metadata.return_value = file_meta("Loaded Gun Full Mix.mp3", "/rC057/Loaded Gun Full Mix.mp3")
        entry = dp.single_file_entry(dbx, "/rc057/loaded gun full mix.mp3")
        self.assertEqual(entry.display_name, "Loaded Gun Full Mix")
        self.assertEqual(entry.mix_type, "full")
        self.assertEqual(entry.category, "full_mix")          # same pipeline as an album track
        self.assertEqual(entry.parent_track, "Loaded Gun Full Mix")
        self.assertEqual(entry.dropbox_path, "/rc057/loaded gun full mix.mp3")

    def test_a_sparse_single_file_keeps_its_mix_type(self):
        dbx = MagicMock()
        dbx.files_get_metadata.return_value = file_meta("Glass Hours Sparse Mix.mp3")
        self.assertEqual(dp.single_file_entry(dbx, "/x.mp3").mix_type, "sparse")


class TestLooseFiles(unittest.TestCase):
    def test_audio_in_a_folder_with_no_subfolders(self):
        dbx = MagicMock()
        dbx.files_list_folder.return_value = MagicMock(
            entries=[file_meta("Tin Weather.mp3"), folder_meta("Artwork"), file_meta("notes.txt"),
                     file_meta("Glass Hours.wav"), file_meta("Riser SDE.aif")],
            has_more=False)
        entries = dp.loose_audio_entries(dbx, "/album")
        self.assertEqual([e.display_name for e in entries], ["Glass Hours", "Riser SDE", "Tin Weather"])
        self.assertEqual([e.mix_type for e in entries], ["full", "sound_design", "full"])

    def test_no_audio_is_an_empty_list(self):
        dbx = MagicMock()
        dbx.files_list_folder.return_value = MagicMock(entries=[file_meta("notes.txt")], has_more=False)
        self.assertEqual(dp.loose_audio_entries(dbx, "/album"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
