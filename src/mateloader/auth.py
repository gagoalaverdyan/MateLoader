from __future__ import annotations

import os
import sys
import urllib.parse
from pathlib import Path

from .constants import APP_NAME, KEYRING_SERVICE, KEYRING_USERNAME, OAUTH_URL


class AuthError(RuntimeError):
    pass


def default_config_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / APP_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_NAME


def keyring_is_available() -> bool:
    try:
        import keyring
        from keyring.errors import KeyringError
    except ImportError:
        return False

    try:
        backend = keyring.get_keyring()
    except KeyringError:
        return False
    backend_name = backend.__class__.__name__.lower()
    return "fail" not in backend_name


def legacy_token_path() -> Path:
    return Path("token.txt")


def legacy_config_token_path() -> Path:
    return default_config_dir() / "token.txt"


def legacy_token_paths() -> tuple[Path, ...]:
    return (legacy_token_path(), legacy_config_token_path())


def read_saved_token() -> str | None:
    env_token = os.environ.get("MATELOADER_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    env_token = os.environ.get("BOOKMATE_AUTH_TOKEN", "").strip()
    if env_token:
        return env_token

    if not keyring_is_available():
        return None

    import keyring
    from keyring.errors import KeyringError

    try:
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
    except KeyringError as exc:
        raise AuthError(f"Failed to read auth token from keyring: {exc}") from exc
    return token.strip() if token else None


def save_auth_token(token: str) -> str:
    clean_token = token.strip()
    if not clean_token:
        raise AuthError("Authentication did not return a token.")

    if not keyring_is_available():
        raise AuthError(
            "No system keyring backend is available. Use MATELOADER_AUTH_TOKEN for non-persistent auth."
        )

    import keyring
    from keyring.errors import KeyringError

    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, clean_token)
    except KeyringError as exc:
        raise AuthError(f"Failed to save auth token to keyring: {exc}") from exc
    return "system keyring"


def migrate_legacy_token() -> bool:
    if not keyring_is_available():
        return False

    for path in legacy_token_paths():
        if not path.is_file():
            continue
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            path.unlink(missing_ok=True)
            continue
        save_auth_token(token)
        path.unlink(missing_ok=True)
        return True
    return False


def run_auth_webview() -> str:
    import webview

    def on_loaded(window):
        parsed = urllib.parse.urlparse(window.get_current_url())
        if "yx4483e97bab6e486a9822973109a14d05.oauth.yandex.ru" not in parsed.netloc:
            return
        fragment = urllib.parse.parse_qs(parsed.fragment)
        tokens = fragment.get("access_token")
        if not tokens:
            return
        window.auth_token = tokens[0]
        window.destroy()

    window = webview.create_window("Yandex Login", OAUTH_URL)
    window.events.loaded += on_loaded
    window.auth_token = None
    webview.start()

    if not window.auth_token:
        raise AuthError("Authentication was cancelled before a token was captured.")
    return window.auth_token


def get_auth_token(
    *,
    allow_webview: bool = True,
) -> str:
    migrated = migrate_legacy_token()
    saved_token = read_saved_token()
    if saved_token:
        return saved_token
    if migrated:
        saved_token = read_saved_token()
        if saved_token:
            return saved_token

    if not allow_webview:
        raise AuthError(
            "No auth token is available. Run `mateloader auth` first."
        )

    token = run_auth_webview()
    save_auth_token(token)
    return token
