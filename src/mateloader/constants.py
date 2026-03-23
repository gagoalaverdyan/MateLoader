from __future__ import annotations

import random

APP_NAME = "MateLoader"
KEYRING_SERVICE = "MateLoader"
KEYRING_USERNAME = "default"
BASE_URL = "https://api.bookmate.yandex.net/api/v5"
OAUTH_URL = (
    "https://oauth.yandex.ru/authorize"
    "?response_type=token&client_id=4483e97bab6e486a9822973109a14d05"
)

DOWNLOAD_COMMANDS = ("book", "audiobook", "comicbook", "serial", "series")

RESOURCE_URLS = {
    "book": {
        "info_url": f"{BASE_URL}/books/{{uuid}}",
        "content_url": f"{BASE_URL}/books/{{uuid}}/content/v4",
    },
    "audiobook": {
        "info_url": f"{BASE_URL}/audiobooks/{{uuid}}",
        "content_url": f"{BASE_URL}/audiobooks/{{uuid}}/playlists.json",
    },
    "comicbook": {
        "info_url": f"{BASE_URL}/comicbooks/{{uuid}}",
        "content_url": f"{BASE_URL}/comicbooks/{{uuid}}/metadata.json",
    },
    "serial": {
        "info_url": f"{BASE_URL}/books/{{uuid}}",
        "content_url": f"{BASE_URL}/books/{{uuid}}/episodes",
    },
    "series": {
        "info_url": f"{BASE_URL}/series/{{uuid}}",
        "content_url": f"{BASE_URL}/series/{{uuid}}/parts",
    },
}

USER_AGENTS = (
    "Samsung/Galaxy_A51 Android/12 Bookmate/3.7.3",
    "Huawei/P40_Lite Android/11 Bookmate/3.7.3",
    "OnePlus/Nord_N10 Android/10 Bookmate/3.7.3",
)

HEADER_TEMPLATE = {
    "app-user-agent": "",
    "mcc": "",
    "mnc": "",
    "imei": "",
    "subscription-country": "",
    "app-locale": "",
    "bookmate-version": "",
    "bookmate-websocket-version": "",
    "device-idfa": "",
    "onyx-preinstall": "false",
    "auth-token": "",
    "accept-encoding": "",
    "user-agent": "",
}


def build_headers(auth_token: str) -> dict[str, str]:
    headers = dict(HEADER_TEMPLATE)
    headers["app-user-agent"] = random.choice(USER_AGENTS)
    headers["auth-token"] = auth_token.strip()
    return headers
