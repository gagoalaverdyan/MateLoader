from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from mateloader.downloader import Downloader, DownloaderError


class DownloaderTests(unittest.TestCase):
    def test_base_path_uses_collection_segments_and_sanitizes_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = Downloader(auth_token="token", output_root=Path(temp_dir))

            base_path = downloader._base_path(
                "book",
                'Title: With / Invalid*Chars?',
                collection=("Series Name", "Part: 1"),
            )

            expected = (
                Path(temp_dir)
                / "series"
                / "Series Name"
                / "Part 1"
                / "Title With  InvalidChars"
                / "Title With  InvalidChars"
            )
            self.assertEqual(base_path, expected)
            self.assertTrue(base_path.parent.is_dir())

    def test_run_dispatches_max_bitrate_to_audiobook_download(self) -> None:
        downloader = Downloader(auth_token="token")

        with mock.patch.object(
            Downloader, "download_audiobook", autospec=True
        ) as download_audiobook:
            downloader.run("audiobook", "abc123", max_bitrate=True, collection=("Series",))

        download_audiobook.assert_called_once_with(
            downloader,
            "abc123",
            collection=("Series",),
            max_bitrate=True,
        )

    def test_get_resource_info_rejects_missing_metadata(self) -> None:
        downloader = Downloader(auth_token="token")

        with mock.patch.object(Downloader, "_request_json", return_value={}):
            with self.assertRaises(DownloaderError):
                downloader._get_resource_info("book", "missing-id")

    def test_safe_extract_archive_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive_path = Path(temp_dir) / "comic.zip"
            destination = Path(temp_dir) / "extract"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "bad")

            downloader = Downloader(auth_token="token", output_root=Path(temp_dir))
            with self.assertRaises(DownloaderError):
                downloader._safe_extract_archive(archive_path, destination)
