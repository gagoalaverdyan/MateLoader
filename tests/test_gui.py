from __future__ import annotations

import unittest

from mateloader.gui import parse_resource_url


class GuiTests(unittest.TestCase):
    def test_parse_resource_url_extracts_book_type_and_id(self) -> None:
        command, uuid = parse_resource_url("https://books.yandex.ru/books/QAvzorqj")

        self.assertEqual(command, "book")
        self.assertEqual(uuid, "QAvzorqj")

    def test_parse_resource_url_accepts_urls_without_scheme(self) -> None:
        command, uuid = parse_resource_url("books.yandex.ru/audiobooks/abc123")

        self.assertEqual(command, "audiobook")
        self.assertEqual(uuid, "abc123")

    def test_parse_resource_url_rejects_unsupported_hosts(self) -> None:
        with self.assertRaisesRegex(ValueError, "books.yandex.ru"):
            parse_resource_url("https://example.com/books/QAvzorqj")

    def test_parse_resource_url_rejects_missing_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "resource type and ID"):
            parse_resource_url("https://books.yandex.ru/books")
