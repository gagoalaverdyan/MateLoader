from __future__ import annotations

import json
import re
import tempfile
import time
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .auth import require_auth_token
from .constants import DOWNLOAD_COMMANDS, RESOURCE_URLS, build_headers

if TYPE_CHECKING:
    import httpx

StatusCallback = Callable[[str], None]
# (current, total, label). ``total`` of 0 means the count is unknown and the UI
# should fall back to an indeterminate/pulsing indicator.
ProgressCallback = Callable[[int, int, str], None]

DEFAULT_OUTPUT_ROOT = Path("mybooks")
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2
RETRIABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
IMAGE_SUFFIXES = {".jpeg", ".jpg", ".png"}


class DownloaderError(RuntimeError):
    pass


def emit_status(message: str, callback: StatusCallback | None = None) -> None:
    if callback is not None:
        callback(message)
        return
    print(message)


def sanitize_filename(filename: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]', "", filename).strip().rstrip(".")
    return sanitized or "untitled"


def create_pdf_from_images(
    images_folder: Path,
    output_pdf: Path,
    progress_callback: StatusCallback | None = None,
) -> None:
    from PIL import Image
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    pdf = canvas.Canvas(str(output_pdf), pagesize=letter)
    width, height = letter

    images = sorted(
        path for path in images_folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES
    )
    if not images:
        raise DownloaderError("No comicbook images were found in the downloaded archive.")

    for image_path in images:
        with Image.open(image_path):
            pdf.drawImage(str(image_path), 0, 0, width, height)
            pdf.showPage()

    pdf.save()
    emit_status(f"Saved {output_pdf}", progress_callback)


def epub_to_fb2(
    epub_path: Path,
    fb2_path: Path,
    progress_callback: StatusCallback | None = None,
) -> None:
    import ebooklib
    from bs4 import BeautifulSoup
    from ebooklib import epub

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        book = epub.read_epub(str(epub_path))

    fb2_content = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<fb2 xmlns="http://www.gribuser.ru/xml/fictionbook/2.0" '
        'xmlns:l="http://www.w3.org/1999/xlink">',
        "<body>",
    ]
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        fb2_content.append(f"<p>{soup.get_text()}</p>")

    fb2_content.extend(["</body>", "</fb2>"])
    fb2_path.write_text("\n".join(fb2_content), encoding="utf-8")
    emit_status(f"Saved {fb2_path}", progress_callback)


@dataclass(slots=True)
class Downloader:
    auth_token: str
    output_root: Path | str = DEFAULT_OUTPUT_ROOT
    progress_callback: StatusCallback | None = None
    on_progress: ProgressCallback | None = None
    headers: dict[str, str] = field(init=False)
    _client: httpx.Client | None = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root).expanduser()
        self.headers = build_headers(self.auth_token)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def emit(self, message: str) -> None:
        emit_status(message, self.progress_callback)

    def progress(self, current: int, total: int, label: str) -> None:
        """Report structured progress, if a handler is attached.

        ``total`` of 0 signals an unknown count (indeterminate progress).
        Never raises: a misbehaving UI callback must not break a download.
        """
        if self.on_progress is None:
            return
        try:
            self.on_progress(current, total, label)
        except Exception:  # pragma: no cover - defensive UI boundary
            pass

    def _httpx(self):
        try:
            import httpx
        except ImportError as exc:  # pragma: no cover - dependency issue
            raise DownloaderError(
                "The httpx dependency is required to download content."
            ) from exc
        return httpx

    def _get_client(self):
        if self._client is None:
            httpx = self._httpx()
            timeout = httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=30.0)
            self._client = httpx.Client(
                http2=True,
                follow_redirects=True,
                timeout=timeout,
            )
        return self._client

    def _request(self, url: str, *, download_label: str) -> httpx.Response:
        httpx = self._httpx()
        client = self._get_client()
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.get(url, headers=self.headers)
                if response.status_code in RETRIABLE_STATUS_CODES:
                    last_error = DownloaderError(
                        f"{download_label} returned {response.status_code}"
                    )
                else:
                    response.raise_for_status()
                    return response
            except httpx.HTTPError as exc:
                last_error = exc

            if attempt < MAX_ATTEMPTS:
                self.emit(
                    f"{download_label} failed on attempt {attempt}/{MAX_ATTEMPTS}; retrying..."
                )
                time.sleep(RETRY_DELAY_SECONDS)

        raise DownloaderError(
            f"{download_label} failed after {MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def _request_json(self, url: str, *, download_label: str) -> dict:
        response = self._request(url, download_label=download_label)
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise DownloaderError(f"{download_label} returned invalid JSON.") from exc
        if not isinstance(payload, dict):
            raise DownloaderError(f"{download_label} returned an unexpected response.")
        return payload

    def _download_file(self, url: str, file_path: Path) -> None:
        httpx = self._httpx()
        client = self._get_client()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = file_path.parent / f"{file_path.name}.part"
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                with client.stream("GET", url, headers=self.headers) as response:
                    if response.status_code in RETRIABLE_STATUS_CODES:
                        last_error = DownloaderError(
                            f"Downloading {file_path.name} returned {response.status_code}"
                        )
                    else:
                        response.raise_for_status()
                        with temp_path.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                handle.write(chunk)
                        temp_path.replace(file_path)
                        self.emit(f"Saved {file_path}")
                        return
            except httpx.HTTPError as exc:
                last_error = exc
            finally:
                temp_path.unlink(missing_ok=True)

            if attempt < MAX_ATTEMPTS:
                self.emit(
                    f"Downloading {file_path.name} failed on attempt "
                    f"{attempt}/{MAX_ATTEMPTS}; retrying..."
                )
                time.sleep(RETRY_DELAY_SECONDS)

        raise DownloaderError(
            f"Failed to download {file_path.name} after {MAX_ATTEMPTS} attempts: {last_error}"
        ) from last_error

    def _base_path(
        self,
        resource_type: str,
        title: str,
        collection: tuple[str, ...] = (),
    ) -> Path:
        clean_title = sanitize_filename(title)
        category = "series" if collection else resource_type
        base_dir = self.output_root / category
        for segment in collection:
            base_dir = base_dir / sanitize_filename(segment)
        resource_dir = base_dir / clean_title
        resource_dir.mkdir(parents=True, exist_ok=True)
        return resource_dir / clean_title

    def _get_resource_info(
        self,
        resource_type: str,
        uuid: str,
        collection: tuple[str, ...] = (),
    ) -> Path:
        info_url = RESOURCE_URLS[resource_type]["info_url"].format(uuid=uuid)
        info = self._request_json(
            info_url,
            download_label=f"Fetching metadata for {resource_type} {uuid}",
        )
        resource = info.get(resource_type)
        if not isinstance(resource, dict):
            raise DownloaderError(f"Failed to fetch metadata for {resource_type} {uuid}")

        cover = resource.get("cover")
        if not isinstance(cover, dict) or not cover.get("large"):
            raise DownloaderError(f"{resource_type} {uuid} is missing cover metadata.")

        title = resource.get("title")
        if not isinstance(title, str) or not title.strip():
            raise DownloaderError(f"{resource_type} {uuid} is missing a title.")

        base_path = self._base_path(resource_type, title, collection)
        self._download_file(str(cover["large"]), base_path.with_suffix(".jpeg"))
        base_path.with_suffix(".json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.emit(f"Saved {base_path.with_suffix('.json')}")
        return base_path

    def _get_resource_json(self, resource_type: str, uuid: str) -> dict:
        content_url = RESOURCE_URLS[resource_type]["content_url"].format(uuid=uuid)
        return self._request_json(
            content_url,
            download_label=f"Fetching content for {resource_type} {uuid}",
        )

    def _safe_extract_archive(self, archive_path: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.infolist():
                extracted_path = destination / member.filename
                resolved_destination = destination.resolve()
                resolved_target = extracted_path.resolve()
                if resolved_destination not in resolved_target.parents and (
                    resolved_target != resolved_destination
                ):
                    raise DownloaderError(
                        f"Archive member {member.filename!r} would escape the target directory."
                    )
            archive.extractall(destination)

    def download_book(
        self,
        uuid: str,
        *,
        collection: tuple[str, ...] = (),
        base_path: Path | None = None,
    ) -> None:
        # Only a top-level book drives the progress bar; when nested inside a
        # serial or series the parent reports item-level progress instead.
        steps = base_path is None and not collection
        if steps:
            self.progress(0, 3, "Fetching book metadata")
        target_base_path = (
            base_path if base_path is not None else self._get_resource_info("book", uuid, collection)
        )
        if steps:
            self.progress(1, 3, "Downloading book")
        self._download_file(
            RESOURCE_URLS["book"]["content_url"].format(uuid=uuid),
            target_base_path.with_suffix(".epub"),
        )
        if steps:
            self.progress(2, 3, "Converting to FB2")
        epub_to_fb2(
            target_base_path.with_suffix(".epub"),
            target_base_path.with_suffix(".fb2"),
            self.progress_callback,
        )
        if steps:
            self.progress(3, 3, "Book complete")

    def download_audiobook(
        self,
        uuid: str,
        *,
        collection: tuple[str, ...] = (),
        max_bitrate: bool = False,
    ) -> None:
        steps = not collection
        if steps:
            self.progress(0, 0, "Fetching audiobook metadata")
        base_path = self._get_resource_info("audiobook", uuid, collection)
        response = self._get_resource_json("audiobook", uuid)
        bitrate_key = "max_bit_rate" if max_bitrate else "min_bit_rate"

        tracks = response.get("tracks", [])
        total = len(tracks)
        for index, track in enumerate(tracks, start=1):
            if steps:
                self.progress(index - 1, total, f"Track {index} of {total}")
            chapter_name = sanitize_filename(f'Глава_{track["number"] + 1}') + ".m4a"
            destination = base_path.parent / chapter_name
            if destination.exists():
                if steps:
                    self.progress(index, total, f"Track {index} of {total} (cached)")
                continue
            download_url = track["offline"][bitrate_key]["url"].replace(".m3u8", ".m4a")
            self._download_file(download_url, destination)
            if steps:
                self.progress(index, total, f"Track {index} of {total}")

    def download_comicbook(
        self,
        uuid: str,
        *,
        collection: tuple[str, ...] = (),
    ) -> None:
        steps = not collection
        if steps:
            self.progress(0, 3, "Fetching comicbook metadata")
        base_path = self._get_resource_info("comicbook", uuid, collection)
        response = self._get_resource_json("comicbook", uuid)
        archive_path = base_path.with_suffix(".cbr")
        if steps:
            self.progress(1, 3, "Downloading comicbook archive")
        self._download_file(response["uris"]["zip"], archive_path)

        with tempfile.TemporaryDirectory(prefix="mateloader-comic-") as temp_dir:
            extract_dir = Path(temp_dir)
            self._safe_extract_archive(archive_path, extract_dir)
            if steps:
                self.progress(2, 3, "Rendering PDF")
            create_pdf_from_images(
                extract_dir,
                base_path.with_suffix(".pdf"),
                self.progress_callback,
            )
        if steps:
            self.progress(3, 3, "Comicbook complete")

    def download_serial(
        self,
        uuid: str,
        *,
        collection: tuple[str, ...] = (),
    ) -> None:
        steps = not collection
        if steps:
            self.progress(0, 0, "Fetching serial metadata")
        base_path = self._get_resource_info("book", uuid, collection)
        response = self._get_resource_json("serial", uuid)
        episodes = response.get("episodes", [])
        total = len(episodes)
        for index, episode in enumerate(episodes, start=1):
            if steps:
                self.progress(index - 1, total, f"Episode {index} of {total}")
            episode_title = sanitize_filename(episode["title"])
            episode_name = f"{index}. {episode_title}"
            episode_dir = base_path.parent / episode_name
            episode_dir.mkdir(parents=True, exist_ok=True)
            self.download_book(
                episode["uuid"],
                base_path=episode_dir / episode_name,
            )
            if steps:
                self.progress(index, total, f"Episode {index} of {total}")

    def download_series(
        self,
        uuid: str,
        *,
        collection: tuple[str, ...] = (),
    ) -> None:
        steps = not collection
        if steps:
            self.progress(0, 0, "Fetching series metadata")
        base_path = self._get_resource_info("series", uuid, collection)
        response = self._get_resource_json("series", uuid)
        series_name = base_path.name
        child_collection = (*collection, series_name)

        parts = response.get("parts", [])
        total = len(parts)
        for index, part in enumerate(parts, start=1):
            resource_type = part["resource_type"]
            resource_uuid = part["resource"]["uuid"]
            if steps:
                self.progress(index - 1, total, f"Part {index} of {total} ({resource_type})")
            self.emit(f"{resource_type} {resource_uuid}")
            self.run(resource_type, resource_uuid, collection=child_collection)
            if steps:
                self.progress(index, total, f"Part {index} of {total}")

    def run(
        self,
        command: str,
        uuid: str,
        *,
        max_bitrate: bool = False,
        collection: tuple[str, ...] = (),
    ) -> None:
        if command not in DOWNLOAD_COMMANDS:
            raise DownloaderError(f"Unsupported command: {command}")

        if command == "book":
            self.download_book(uuid, collection=collection)
            return
        if command == "audiobook":
            self.download_audiobook(
                uuid,
                collection=collection,
                max_bitrate=max_bitrate,
            )
            return
        if command == "comicbook":
            self.download_comicbook(uuid, collection=collection)
            return
        if command == "serial":
            self.download_serial(uuid, collection=collection)
            return
        self.download_series(uuid, collection=collection)


def run_download(
    command: str,
    uuid: str,
    *,
    max_bitrate: bool = False,
    auth_token: str | None = None,
    output_root: Path | str = DEFAULT_OUTPUT_ROOT,
    progress_callback: StatusCallback | None = None,
    on_progress: ProgressCallback | None = None,
) -> None:
    token = auth_token.strip() if auth_token else require_auth_token()
    downloader = Downloader(
        auth_token=token,
        output_root=output_root,
        progress_callback=progress_callback,
        on_progress=on_progress,
    )
    try:
        downloader.run(command, uuid, max_bitrate=max_bitrate)
    finally:
        downloader.close()
