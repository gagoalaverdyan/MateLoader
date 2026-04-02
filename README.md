# MateLoader

MateLoader is a simple downloader for Yandex Books with two ways to use it:

- a small desktop app
- a CLI for terminal-driven workflows

The desktop app is the primary mode. Install it, sign in once, paste an ID, and download.

Supported resource types:

- books
- audiobooks
- comicbooks
- serials
- series

## Install

Core install, with the downloader and CLI commands:

```bash
pip install .
```

That gives you:

- `mateloader`

Interactive authentication for the CLI:

```bash
pip install '.[auth]'
```

Desktop app and interactive authentication:

```bash
pip install '.[gui]'
```

Source install with the core CLI dependencies:

```bash
pip install -r requirements-cli.txt
pip install --no-deps .
```

Developer tooling:

```bash
pip install '.[dev]'
```

## Use The Desktop App

Start it:

```bash
mateloader-gui
```

If you installed only the core package, the GUI entrypoint will exit with a message telling you to install `mateloader[gui]`.

Step by step:

1. Click `Authenticate`
2. Sign in with your Yandex account
3. Choose the resource type
4. Paste the ID from the Yandex Books URL
5. Leave `Token` empty to use the stored token, or paste a temporary override token
6. For audiobooks, enable `Max quality` if needed
7. Click `Download`

The app is intentionally minimal: one window, one form, and a plain log panel for progress.

## Use The CLI

If you prefer the terminal, use:

```bash
mateloader <command> [options]
```

Available commands:

| Command | What it does |
| --- | --- |
| `auth` | Opens the login flow and saves your token |
| `book` | Downloads a text book as `.epub` and `.fb2` |
| `audiobook` | Downloads audiobook tracks |
| `comicbook` | Downloads a comicbook and renders a `.pdf` |
| `serial` | Downloads a serialized book episode by episode |
| `series` | Downloads every part in a series |

Step by step:

1. Run `mateloader auth` if you installed `mateloader[auth]`
2. Copy the ID from a Yandex Books URL
3. Run the matching command

Examples:

```bash
mateloader auth
mateloader book <id>
mateloader audiobook <id> --max-bitrate
mateloader comicbook <id> --output-dir downloads
MATELOADER_AUTH_TOKEN=... mateloader series <id>
```

## Find The ID

Take it from the Yandex Books URL:

```text
https://books.yandex.ru/<type>/<id>
```

Examples:

- `https://books.yandex.ru/books/abcd1234`
- `https://books.yandex.ru/audiobooks/abcd1234`
- `https://books.yandex.ru/series/abcd1234`

The `<type>` part tells you what to select in the GUI or which CLI command to run.

## Authentication

MateLoader stores your token in the system keyring.

Downloads do not launch the browser automatically anymore. They read a token from:

1. `MATELOADER_AUTH_TOKEN`
2. `BOOKMATE_AUTH_TOKEN`
3. the system keyring

You can also pass a token directly:

```bash
mateloader book <id> --auth-token <token>
```

Or use an environment variable:

```bash
MATELOADER_AUTH_TOKEN=<token> mateloader book <id>
```

If you do not want to install the optional auth dependencies, using an environment variable is enough for CLI downloads.

If an old `token.txt` is present, MateLoader migrates it automatically and removes it.

## Run From The Repo

Without installing:

```bash
PYTHONPATH=src python3 scripts/legacy_gui.py
PYTHONPATH=src python3 scripts/legacy_cli.py book <id>
```

## Build

Create distributable packages:

```bash
python -m build
```

Validate them:

```bash
python -m twine check dist/*
```

Run the test suite:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests
```
