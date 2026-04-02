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


def _read_env_token() -> str | None:
    for variable_name in ("MATELOADER_AUTH_TOKEN", "BOOKMATE_AUTH_TOKEN"):
        token = os.environ.get(variable_name, "").strip()
        if token:
            return token
    return None


def read_saved_token() -> str | None:
    env_token = _read_env_token()
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


def get_saved_auth_token() -> str | None:
    migrate_legacy_token()
    return read_saved_token()


def require_auth_token() -> str:
    token = get_saved_auth_token()
    if token:
        return token
    raise AuthError(
        "No auth token is available. Run `mateloader auth`, use the GUI Authenticate button, "
        "or set MATELOADER_AUTH_TOKEN."
    )


def run_auth_webview() -> str:
    try:
        import webview
    except ImportError as exc:
        raise AuthError(
            "Interactive authentication requires the optional webview dependency. "
            "Install `mateloader[auth]` or set MATELOADER_AUTH_TOKEN manually."
        ) from exc

    auth_token: str | None = None

    def read_js_value(expression: str) -> str:
        try:
            value = window.evaluate_js(expression)
        except Exception:  # pragma: no cover - depends on webview backend
            return ""
        if isinstance(value, str):
            return value
        return ""

    def extract_token_from_url(raw_url: str) -> str | None:
        if not raw_url:
            return None
        parsed = urllib.parse.urlparse(raw_url)
        fragment = urllib.parse.parse_qs(parsed.fragment)
        tokens = fragment.get("access_token")
        if not tokens:
            return None
        return tokens[0]

    def on_loaded(*_args):
        nonlocal auth_token

        current_url = ""
        try:
            current_url = window.get_current_url() or ""
        except Exception:  # pragma: no cover - depends on webview backend
            pass

        href = read_js_value("window.location.href")
        hash_value = read_js_value("window.location.hash")

        auth_token = (
            extract_token_from_url(current_url)
            or extract_token_from_url(href)
            or extract_token_from_url(f"https://dummy.invalid/{hash_value}")
        )
        if not auth_token:
            return

        window.destroy()

    window = webview.create_window("Yandex Login", OAUTH_URL)
    window.events.loaded += on_loaded
    webview.start()

    if not auth_token:
        raise AuthError("Authentication was cancelled before a token was captured.")
    return auth_token


def authenticate_user() -> str:
    token = run_auth_webview()
    save_auth_token(token)
    return token
