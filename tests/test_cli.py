from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from mateloader import cli


class CliTests(unittest.TestCase):
    def test_auth_command_prints_saved_message(self) -> None:
        with mock.patch("mateloader.cli.authenticate_user", return_value="token-123"):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = cli._run_auth_command(show_token=False)

        self.assertEqual(exit_code, 0)
        self.assertEqual(buffer.getvalue().strip(), "Saved token to system keyring")

    def test_download_command_forwards_arguments(self) -> None:
        args = mock.Mock(
            command="book",
            uuid="resource-id",
            max_bitrate=False,
            auth_token="manual-token",
            output_dir=Path("downloads"),
        )

        with mock.patch("mateloader.cli.run_download") as run_download:
            exit_code = cli._run_download_command(args)

        self.assertEqual(exit_code, 0)
        run_download.assert_called_once_with(
            "book",
            "resource-id",
            max_bitrate=False,
            auth_token="manual-token",
            output_root=Path("downloads"),
        )
