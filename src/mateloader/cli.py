from __future__ import annotations

import argparse
from pathlib import Path

from .auth import AuthError, authenticate_user
from .constants import DOWNLOAD_COMMANDS
from .downloader import DEFAULT_OUTPUT_ROOT, DownloaderError, run_download


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mateloader",
        description="Download supported Yandex Books resources from the command line.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser(
        "auth",
        help="Open the Yandex login flow and save a token in the system keyring.",
    )
    auth_parser.add_argument(
        "--show-token",
        action="store_true",
        help="Print the captured token after saving it. Avoid this on shared machines.",
    )

    for command in DOWNLOAD_COMMANDS:
        command_parser = subparsers.add_parser(
            command,
            help=f"Download a {command} resource.",
        )
        command_parser.add_argument("uuid", help="Resource ID from the Yandex Books URL.")
        command_parser.add_argument(
            "--output-dir",
            type=Path,
            default=DEFAULT_OUTPUT_ROOT,
            help="Directory where downloaded files will be written.",
        )
        command_parser.add_argument(
            "--auth-token",
            default=None,
            help="Use an auth token directly instead of reading it from the system keyring.",
        )
        if command == "audiobook":
            command_parser.add_argument(
                "--max-bitrate",
                action="store_true",
                help="Download audiobook tracks in the highest available bitrate.",
            )

    return parser


def _run_auth_command(show_token: bool) -> int:
    token = authenticate_user()
    print("Saved token to system keyring")
    if show_token:
        print(token)
    return 0


def _run_download_command(args: argparse.Namespace) -> int:
    run_download(
        args.command,
        args.uuid,
        max_bitrate=getattr(args, "max_bitrate", False),
        auth_token=args.auth_token,
        output_root=args.output_dir,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "auth":
            return _run_auth_command(args.show_token)
        return _run_download_command(args)
    except (AuthError, DownloaderError) as exc:
        parser.exit(status=1, message=f"{exc}\n")


def legacy_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/legacy_cli.py",
        description="Legacy entry point for the packaged MateLoader CLI.",
    )
    parser.add_argument("command", choices=DOWNLOAD_COMMANDS)
    parser.add_argument("uuid")
    parser.add_argument("--max_bitrate", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--auth-token", default=None)
    args = parser.parse_args(argv)

    try:
        return _run_download_command(args)
    except (AuthError, DownloaderError) as exc:
        parser.exit(status=1, message=f"{exc}\n")
