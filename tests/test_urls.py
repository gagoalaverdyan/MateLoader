from __future__ import annotations

import unittest

from mateloader.urls import COMMAND_LABELS, parse_resource_url


class UrlParsingTests(unittest.TestCase):
    def test_extracts_book_type_and_id(self) -> None:
        command, uuid = parse_resource_url("https://books.yandex.ru/books/QAvzorqj")
        self.assertEqual(command, "book")
        self.assertEqual(uuid, "QAvzorqj")

    def test_accepts_urls_without_scheme(self) -> None:
        command, uuid = parse_resource_url("books.yandex.ru/audiobooks/abc123")
        self.assertEqual(command, "audiobook")
        self.assertEqual(uuid, "abc123")

    def test_strips_www_prefix(self) -> None:
        command, uuid = parse_resource_url("https://www.books.yandex.ru/series/xyz")
        self.assertEqual(command, "series")
        self.assertEqual(uuid, "xyz")

    def test_rejects_unsupported_hosts(self) -> None:
        with self.assertRaisesRegex(ValueError, "books.yandex.ru"):
            parse_resource_url("https://example.com/books/QAvzorqj")

    def test_rejects_missing_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "resource type and ID"):
            parse_resource_url("https://books.yandex.ru/books")

    def test_rejects_unknown_type(self) -> None:
        with self.assertRaisesRegex(ValueError, "not supported"):
            parse_resource_url("https://books.yandex.ru/magazines/abc")

    def test_rejects_empty(self) -> None:
        with self.assertRaisesRegex(ValueError, "Paste"):
            parse_resource_url("   ")

    def test_every_command_has_a_label(self) -> None:
        for command in set(COMMAND_LABELS):
            self.assertTrue(COMMAND_LABELS[command])


if __name__ == "__main__":
    unittest.main()
