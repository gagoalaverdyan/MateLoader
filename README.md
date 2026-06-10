<div align="center">

<img src="data/icons/hicolor/scalable/apps/io.github.gagoalaverdyan.MateLoader.svg" width="120" alt="MateLoader icon" />

# MateLoader

**A clean GTK4 desktop app and CLI for downloading Yandex Books content.**

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB)
![GTK4 + libadwaita](https://img.shields.io/badge/GTK4-libadwaita-4A90D9)

</div>

---

Paste a link, pick a folder, download. MateLoader supports **books, audiobooks,
comicbooks, serials, and series** — with a live progress bar and an optional
detailed log. The desktop app follows the GNOME Human Interface Guidelines; a
CLI is included for terminal workflows.

## Features

- **Paste and go** — drop a `books.yandex.ru` link and the type is detected as you type.
- **Choose your folder** — a native picker sets where files land (defaults to `~/Downloads/MateLoader`).
- **Real progress** — a progress bar tracks multi-part downloads, with toasts for results.
- **Sign in once** — your token is stored in the system keyring; the app stays locked until you authenticate.

## Install

**1. System libraries** (GTK 4 + libadwaita are installed by your OS, not pip):

| Platform | Command |
| --- | --- |
| Fedora | `sudo dnf install gtk4 libadwaita python3-gobject` |
| Debian / Ubuntu | `sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 libadwaita-1-0 python3-gi python3-gi-cairo` |
| Arch | `sudo pacman -S gtk4 libadwaita python-gobject` |
| macOS (Homebrew) | `brew install gtk4 libadwaita pygobject3 adwaita-icon-theme` |

**2. The app:**

```bash
pip install '.[gui]'   # desktop app + auth
pip install .          # CLI only
```

> On Debian/Ubuntu and Fedora, `python3-gi` / `python3-gobject` already provide
> the PyGObject binding, so `pip install .` is enough.

**3. Run it:**

```bash
mateloader-gui
```

## Using the app

1. **Authenticate** with your Yandex account (or paste a token override).
2. **Paste** a Yandex Books URL — type and ID are detected automatically.
3. **Pick** a download folder (optional).
4. **Download.**

Find the ID in any Yandex Books URL: `https://books.yandex.ru/<type>/<id>`.

<details>
<summary><b>Command line</b></summary>

```bash
mateloader <command> [options]
```

| Command | What it does |
| --- | --- |
| `auth` | Opens the login flow and saves your token |
| `book` | Downloads a text book as `.epub` and `.fb2` |
| `audiobook` | Downloads audiobook tracks (`--max-bitrate` for top quality) |
| `comicbook` | Downloads a comicbook and renders a `.pdf` |
| `serial` | Downloads a serialized book episode by episode |
| `series` | Downloads every part in a series |

```bash
mateloader auth
mateloader book <id>
mateloader audiobook <id> --max-bitrate
MATELOADER_AUTH_TOKEN=... mateloader series <id>
```

</details>

<details>
<summary><b>Authentication details</b></summary>

The token is read, in order, from `MATELOADER_AUTH_TOKEN`, `BOOKMATE_AUTH_TOKEN`,
then the system keyring. You can also pass one directly with `--auth-token`. An
environment variable alone is enough for CLI downloads without the optional auth
extras. A legacy `token.txt`, if present, is migrated automatically.

</details>

<details>
<summary><b>Desktop integration (Linux)</b></summary>

Install the bundled launcher, icon, and AppStream metadata:

```bash
install -Dm644 data/io.github.gagoalaverdyan.MateLoader.desktop \
  ~/.local/share/applications/io.github.gagoalaverdyan.MateLoader.desktop
install -Dm644 data/icons/hicolor/scalable/apps/io.github.gagoalaverdyan.MateLoader.svg \
  ~/.local/share/icons/hicolor/scalable/apps/io.github.gagoalaverdyan.MateLoader.svg
install -Dm644 data/io.github.gagoalaverdyan.MateLoader.metainfo.xml \
  ~/.local/share/metainfo/io.github.gagoalaverdyan.MateLoader.metainfo.xml
```

</details>

<details>
<summary><b>Develop, build, and test</b></summary>

Run from the repo without installing:

```bash
PYTHONPATH=src python3 scripts/legacy_gui.py
PYTHONPATH=src python3 scripts/legacy_cli.py book <id>
```

Build and test:

```bash
pip install '.[dev]'
python -m build
PYTHONPATH=src python3 -m unittest discover -s tests
```

</details>

## License

Released under the [GNU General Public License v3.0 or later](LICENSE).
© 2026 [Gago Alaverdyan](https://github.com/gagoalaverdyan).
