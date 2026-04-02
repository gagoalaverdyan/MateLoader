from __future__ import annotations

import os
import unittest
from unittest import mock

from mateloader.auth import AuthError, authenticate_user, read_saved_token, require_auth_token


class AuthTests(unittest.TestCase):
    def test_read_saved_token_prefers_primary_env_var(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "MATELOADER_AUTH_TOKEN": " primary-token ",
                "BOOKMATE_AUTH_TOKEN": "secondary-token",
            },
            clear=False,
        ):
            self.assertEqual(read_saved_token(), "primary-token")

    def test_require_auth_token_raises_when_no_token_is_available(self) -> None:
        with mock.patch("mateloader.auth.get_saved_auth_token", return_value=None):
            with self.assertRaises(AuthError):
                require_auth_token()

    def test_authenticate_user_runs_webview_and_saves_token(self) -> None:
        with mock.patch(
            "mateloader.auth.run_auth_webview", return_value="captured-token"
        ) as run_auth_webview:
            with mock.patch("mateloader.auth.save_auth_token") as save_auth_token:
                token = authenticate_user()

        self.assertEqual(token, "captured-token")
        run_auth_webview.assert_called_once_with()
        save_auth_token.assert_called_once_with("captured-token")
