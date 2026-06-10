from __future__ import annotations

from urllib.parse import urlparse

URL_TYPE_MAP = {
    "book": "book",
    "books": "book",
    "audiobook": "audiobook",
    "audiobooks": "audiobook",
    "comicbook": "comicbook",
    "comicbooks": "comicbook",
    "serial": "serial",
    "serials": "serial",
    "series": "series",
}

COMMAND_LABELS = {
    "book": "Book",
    "audiobook": "Audiobook",
    "comicbook": "Comicbook",
    "serial": "Serial",
    "series": "Series",
}


def parse_resource_url(url: str) -> tuple[str, str]:
    """Parse a Yandex Books URL into a (command, resource_id) pair.

    Accepts URLs with or without a scheme and tolerates a leading ``www.``.
    Raises ``ValueError`` with a human-friendly message on any problem so the
    GUI and CLI can surface it directly.
    """
    candidate = url.strip()
    if not candidate:
        raise ValueError("Paste a Yandex Books URL.")

    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    if host != "books.yandex.ru":
        raise ValueError("Only books.yandex.ru URLs are supported.")

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise ValueError("The URL must include both the resource type and ID.")

    command = URL_TYPE_MAP.get(path_parts[0].lower())
    if command is None:
        raise ValueError("This Yandex Books URL type is not supported.")

    uuid = path_parts[1].strip()
    if not uuid:
        raise ValueError("The URL is missing the resource ID.")

    return command, uuid
