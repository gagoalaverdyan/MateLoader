from __future__ import annotations

import asyncio
import json
import re
import shutil
import warnings
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .auth import get_auth_token
from .constants import DOWNLOAD_COMMANDS, RESOURCE_URLS, build_headers

StatusCallback = Callable[[str], None]


class DownloaderError(RuntimeError):
    pass


def emit_status(message: str, callback: StatusCallback | None = None) -> None:
    if callback is not None:
        callback(message)
        return
    print(message)


def sanitize_filename(filename: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", filename).strip()


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
        path for path in images_folder.iterdir() if path.suffix.lower() == ".jpeg"
    )
    for image_path in images:
        with Image.open(image_path):
            pdf.drawImage(str(image_path), 0, 0, width, height)
            pdf.showPage()
        image_path.unlink()

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
    output_root: Path | str = Path("mybooks")
    progress_callback: StatusCallback | None = None
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.output_root = Path(self.output_root).expanduser()
        self.headers = build_headers(self.auth_token)

    def emit(self, message: str) -> None:
        emit_status(message, self.progress_callback)

    def _run(self, coroutine):
        return asyncio.run(coroutine)

    async def _download_file(self, url: str, file_path: Path) -> None:
        import httpx

        attempts = 0
        while attempts < 3:
            try:
                async with httpx.AsyncClient(http2=True, verify=False) as client:
                    response = await client.get(url, headers=self.headers, timeout=None)
                    if response.status_code == 200:
                        file_path.parent.mkdir(parents=True, exist_ok=True)
                        file_path.write_bytes(response.content)
                        self.emit(f"Saved {file_path}")
                        return

                    if response.is_redirect and response.next_request is not None:
                        redirected = await client.get(
                            response.next_request.url,
                            headers=self.headers,
                            timeout=None,
                        )
                        if redirected.status_code == 200:
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            file_path.write_bytes(redirected.content)
                            self.emit(f"Saved {file_path}")
                            return

                    self.emit(
                        f"Failed to download file. Status code: {response.status_code}"
                    )
            except httpx.HTTPError as exc:
                self.emit(f"Failed to download file. {exc}")

            attempts += 1
            if attempts == 3:
                raise DownloaderError(
                    "Failed to download the file. Check the ID or try again later."
                )
            await asyncio.sleep(5)

    async def _send_request(self, url: str):
        import httpx

        attempts = 0
        while attempts < 3:
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=self.headers, timeout=None)
                    if response.status_code == 200:
                        return response
                    self.emit(
                        f"Failed to send request. Status code: {response.status_code}"
                    )
            except httpx.HTTPError as exc:
                self.emit(f"Failed to send request. {exc}")

            attempts += 1
            if attempts == 3:
                raise DownloaderError(
                    "Failed to fetch data. Check the ID or try again later."
                )
            await asyncio.sleep(5)

        raise DownloaderError("Request failed unexpectedly.")

    def _base_path(self, resource_type: str, title: str, series: str = "") -> Path:
        clean_title = sanitize_filename(title)
        category = "series" if series else resource_type
        base_dir = self.output_root / category
        if series:
            base_dir = base_dir / Path(series)
        resource_dir = base_dir / clean_title
        resource_dir.mkdir(parents=True, exist_ok=True)
        return resource_dir / clean_title

    def _get_resource_info(self, resource_type: str, uuid: str, series: str = "") -> Path:
        info_url = RESOURCE_URLS[resource_type]["info_url"].format(uuid=uuid)
        info = self._run(self._send_request(info_url)).json()
        resource = info.get(resource_type)
        if not resource:
            raise DownloaderError(f"Failed to fetch metadata for {resource_type} {uuid}")

        cover_url = resource["cover"]["large"]
        base_path = self._base_path(resource_type, resource["title"], series)
        self._run(self._download_file(cover_url, base_path.with_suffix(".jpeg")))
        base_path.with_suffix(".json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.emit(f"Saved {base_path.with_suffix('.json')}")
        return base_path

    def _get_resource_json(self, resource_type: str, uuid: str) -> dict:
        content_url = RESOURCE_URLS[resource_type]["content_url"].format(uuid=uuid)
        return self._run(self._send_request(content_url)).json()

    def download_book(
        self,
        uuid: str,
        *,
        series: str = "",
        serial_path: Path | str | None = None,
    ) -> None:
        base_path = Path(serial_path) if serial_path is not None else self._get_resource_info(
            "book", uuid, series
        )
        self._run(
            self._download_file(
                RESOURCE_URLS["book"]["content_url"].format(uuid=uuid),
                base_path.with_suffix(".epub"),
            )
        )
        epub_to_fb2(
            base_path.with_suffix(".epub"),
            base_path.with_suffix(".fb2"),
            self.progress_callback,
        )

    def download_audiobook(
        self,
        uuid: str,
        *,
        series: str = "",
        max_bitrate: bool = False,
    ) -> None:
        base_path = self._get_resource_info("audiobook", uuid, series)
        response = self._get_resource_json("audiobook", uuid)
        bitrate_key = "max_bit_rate" if max_bitrate else "min_bit_rate"

        for track in response.get("tracks", []):
            chapter_name = sanitize_filename(f'Глава_{track["number"] + 1}') + ".m4a"
            destination = base_path.parent / chapter_name
            if destination.exists():
                continue
            download_url = track["offline"][bitrate_key]["url"].replace(".m3u8", ".m4a")
            self._run(self._download_file(download_url, destination))

    def download_comicbook(self, uuid: str, *, series: str = "") -> None:
        base_path = self._get_resource_info("comicbook", uuid, series)
        response = self._get_resource_json("comicbook", uuid)
        archive_path = base_path.with_suffix(".cbr")
        self._run(self._download_file(response["uris"]["zip"], archive_path))
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(base_path.parent)

        preview_dir = base_path.parent / "preview"
        if preview_dir.exists():
            shutil.rmtree(preview_dir)

        create_pdf_from_images(
            base_path.parent,
            base_path.with_suffix(".pdf"),
            self.progress_callback,
        )

    def download_serial(self, uuid: str, *, series: str = "") -> None:
        base_path = self._get_resource_info("book", uuid, series)
        response = self._get_resource_json("serial", uuid)
        for index, episode in enumerate(response.get("episodes", []), start=1):
            episode_title = sanitize_filename(episode["title"])
            episode_name = f"{index}. {episode_title}"
            episode_dir = base_path.parent / episode_name
            episode_dir.mkdir(parents=True, exist_ok=True)
            self.download_book(
                episode["uuid"],
                serial_path=episode_dir / episode_name,
            )

    def download_series(self, uuid: str, *, series: str = "") -> None:
        base_path = self._get_resource_info("series", uuid, series)
        response = self._get_resource_json("series", uuid)
        series_name = base_path.name
        self.emit(series_name)
        for index, part in enumerate(response.get("parts", []), start=1):
            resource_type = part["resource_type"]
            resource_uuid = part["resource"]["uuid"]
            self.emit(f"{resource_type} {resource_uuid}")
            self.run(
                resource_type,
                resource_uuid,
                series=f"{series_name}/{index}. ",
            )

    def run(
        self,
        command: str,
        uuid: str,
        *,
        max_bitrate: bool = False,
        series: str = "",
    ) -> None:
        if command not in DOWNLOAD_COMMANDS:
            raise DownloaderError(f"Unsupported command: {command}")

        if command == "book":
            self.download_book(uuid, series=series)
            return
        if command == "audiobook":
            self.download_audiobook(uuid, series=series, max_bitrate=max_bitrate)
            return
        if command == "comicbook":
            self.download_comicbook(uuid, series=series)
            return
        if command == "serial":
            self.download_serial(uuid, series=series)
            return
        self.download_series(uuid, series=series)


def run_download(
    command: str,
    uuid: str,
    *,
    max_bitrate: bool = False,
    auth_token: str | None = None,
    output_root: Path | str = Path("mybooks"),
    progress_callback: StatusCallback | None = None,
) -> None:
    token = auth_token.strip() if auth_token else get_auth_token()
    downloader = Downloader(
        auth_token=token,
        output_root=output_root,
        progress_callback=progress_callback,
    )
    downloader.run(command, uuid, max_bitrate=max_bitrate)
