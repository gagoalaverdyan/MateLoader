from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mateloader.downloader import Downloader


class ProgressEventTests(unittest.TestCase):
    def test_progress_forwards_to_handler(self) -> None:
        events: list[tuple[int, int, str]] = []
        downloader = Downloader(
            auth_token="token",
            on_progress=lambda c, t, label: events.append((c, t, label)),
        )

        downloader.progress(1, 4, "Track 1 of 4")

        self.assertEqual(events, [(1, 4, "Track 1 of 4")])

    def test_progress_is_noop_without_handler(self) -> None:
        downloader = Downloader(auth_token="token")
        # Should not raise even though no handler is attached.
        downloader.progress(2, 5, "anything")

    def test_progress_swallows_handler_errors(self) -> None:
        def boom(*_args: object) -> None:
            raise RuntimeError("UI exploded")

        downloader = Downloader(auth_token="token", on_progress=boom)
        # A misbehaving UI callback must never break a download.
        downloader.progress(0, 0, "label")

    def test_audiobook_reports_item_level_progress(self) -> None:
        events: list[tuple[int, int, str]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = Downloader(
                auth_token="token",
                output_root=Path(temp_dir),
                on_progress=lambda c, t, label: events.append((c, t, label)),
            )

            base_path = Path(temp_dir) / "audiobook" / "Title" / "Title"
            base_path.parent.mkdir(parents=True, exist_ok=True)

            tracks = {
                "tracks": [
                    {"number": 0, "offline": {"min_bit_rate": {"url": "a.m3u8"}}},
                    {"number": 1, "offline": {"min_bit_rate": {"url": "b.m3u8"}}},
                ]
            }

            with mock.patch.object(
                Downloader, "_get_resource_info", return_value=base_path
            ), mock.patch.object(
                Downloader, "_get_resource_json", return_value=tracks
            ), mock.patch.object(Downloader, "_download_file") as download_file:
                downloader.download_audiobook("abc123")

            self.assertEqual(download_file.call_count, 2)

        totals = {total for _current, total, _label in events if total > 0}
        self.assertEqual(totals, {2})
        # The final event should report completion of the last track.
        self.assertEqual(events[-1], (2, 2, "Track 2 of 2"))

    def test_nested_collection_suppresses_step_progress(self) -> None:
        events: list[tuple[int, int, str]] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            downloader = Downloader(
                auth_token="token",
                output_root=Path(temp_dir),
                on_progress=lambda c, t, label: events.append((c, t, label)),
            )

            with mock.patch.object(
                Downloader, "_get_resource_info", return_value=Path(temp_dir) / "x"
            ), mock.patch.object(Downloader, "_download_file"), mock.patch(
                "mateloader.downloader.epub_to_fb2"
            ):
                # Called as part of a series/serial → no coarse book steps emitted.
                downloader.download_book("abc", collection=("Series",))

        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
