"""GTK4 + libadwaita desktop front-end for MateLoader.

The interface follows the GNOME Human Interface Guidelines: an adaptive window
with a header bar, boxed-list preference groups, a real progress bar, and toast
notifications. All blocking work (authentication and downloads) runs on worker
threads and marshals UI updates back to the main loop with ``GLib.idle_add``.

Pure helpers (``parse_resource_url`` and friends) live in :mod:`mateloader.urls`
and are re-exported here so that they remain importable without GTK installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from .auth import AuthError, get_saved_auth_token, keyring_is_available
from .constants import APP_ID, APP_NAME
from .downloader import DownloaderError, run_download

# Re-exported for backwards compatibility and unit tests.
from .urls import COMMAND_LABELS, URL_TYPE_MAP, parse_resource_url

__all__ = [
    "COMMAND_LABELS",
    "URL_TYPE_MAP",
    "parse_resource_url",
    "main",
]


def _app_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("mateloader")
        except PackageNotFoundError:
            return "0.0.0"
    except Exception:  # pragma: no cover - importlib always present on 3.10+
        return "0.0.0"


def _default_download_dir() -> Path:
    """Pick a sensible, writable default download location."""
    xdg_download = os.environ.get("XDG_DOWNLOAD_DIR")
    base = Path(xdg_download) if xdg_download else Path.home() / "Downloads"
    if not base.exists():
        base = Path.home()
    return base / "MateLoader"


def _auth_subprocess_command() -> tuple[list[str], dict[str, str]]:
    """Build the command + environment that runs the interactive auth flow."""
    environment = os.environ.copy()
    src_root = str(Path(__file__).resolve().parents[1])
    existing = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        os.pathsep.join((src_root, existing)) if existing else src_root
    )
    return [sys.executable, "-m", "mateloader", "auth"], environment


try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk
except (ImportError, ValueError) as exc:  # pragma: no cover - dependency issue
    GTK_IMPORT_ERROR: Exception | None = exc
else:
    GTK_IMPORT_ERROR = None


if GTK_IMPORT_ERROR is None:

    class MateLoaderWindow(Adw.ApplicationWindow):
        """The single main window of the desktop app."""

        def __init__(self, application: Adw.Application) -> None:
            super().__init__(application=application)

            self.parsed_command: str | None = None
            self.parsed_uuid: str | None = None
            self.output_dir: Path = _default_download_dir()
            self.busy: bool = False
            self._pulse_source: int | None = None
            self._has_stored_token: bool = False
            self._base_account_subtitle: str = "Checking…"
            self._base_account_icon: str = "content-loading-symbolic"

            self.set_title(APP_NAME)
            self.set_default_size(560, 720)
            self.set_size_request(360, 480)

            self._build_ui()
            self._refresh_storage_status()
            self._update_url_details()

        # ------------------------------------------------------------------ UI

        def _build_ui(self) -> None:
            self.toasts = Adw.ToastOverlay()
            self.set_content(self.toasts)

            toolbar_view = Adw.ToolbarView()
            self.toasts.set_child(toolbar_view)

            header = Adw.HeaderBar()
            toolbar_view.add_top_bar(header)

            menu = Gio.Menu()
            menu.append("About MateLoader", "app.about")
            menu_button = Gtk.MenuButton(
                icon_name="open-menu-symbolic",
                menu_model=menu,
                tooltip_text="Main menu",
            )
            header.pack_start(menu_button)

            self.download_button = Gtk.Button(label="Download")
            self.download_button.add_css_class("suggested-action")
            self.download_button.connect("clicked", self._on_download_clicked)
            header.pack_end(self.download_button)

            # Sign-in banner: shown until a token is available, gating the app.
            self.banner = Adw.Banner(
                title="Authenticate or add a token to start downloading"
            )
            self.banner.set_button_label("Authenticate")
            self.banner.connect("button-clicked", self._on_authenticate_clicked)
            self.banner.set_revealed(False)
            toolbar_view.add_top_bar(self.banner)

            scroller = Gtk.ScrolledWindow(
                hexpand=True,
                vexpand=True,
                hscrollbar_policy=Gtk.PolicyType.NEVER,
            )
            toolbar_view.set_content(scroller)

            clamp = Adw.Clamp(maximum_size=620, tightening_threshold=480)
            scroller.set_child(clamp)

            page = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=18,
                margin_top=24,
                margin_bottom=24,
                margin_start=12,
                margin_end=12,
            )
            clamp.set_child(page)

            # Authentication leads: the rest of the app is gated behind it.
            page.append(self._build_account_group())
            self.source_group = self._build_source_group()
            self.options_group = self._build_options_group()
            page.append(self.source_group)
            page.append(self.options_group)
            page.append(self._build_progress_group())

        def _build_source_group(self) -> Adw.PreferencesGroup:
            group = Adw.PreferencesGroup(
                title="Source",
                description="Paste a Yandex Books link — the type is detected for you.",
            )

            self.url_row = Adw.EntryRow(title="Yandex Books URL")
            self.url_row.set_show_apply_button(False)
            self.url_row.connect("changed", lambda *_: self._update_url_details())
            self.url_row.connect("entry-activated", self._on_download_clicked)
            group.add(self.url_row)

            self.detected_row = Adw.ActionRow(
                title="Detected", subtitle="Waiting for a URL"
            )
            self.detected_icon = Gtk.Image.new_from_icon_name(
                "content-loading-symbolic"
            )
            self.detected_row.add_suffix(self.detected_icon)
            group.add(self.detected_row)

            return group

        def _build_options_group(self) -> Adw.PreferencesGroup:
            group = Adw.PreferencesGroup(title="Options")

            self.folder_row = Adw.ActionRow(
                title="Download folder",
                subtitle=str(self.output_dir),
            )
            self.folder_row.set_activatable(True)
            choose_button = Gtk.Button(
                icon_name="folder-open-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="Choose download folder",
            )
            choose_button.add_css_class("flat")
            choose_button.connect("clicked", self._on_choose_folder)
            self.folder_row.add_suffix(choose_button)
            self.folder_row.set_activatable_widget(choose_button)
            group.add(self.folder_row)

            self.quality_row = Adw.ActionRow(
                title="Maximum audiobook quality",
                subtitle="Only applies to audiobooks",
            )
            self.quality_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
            self.quality_row.add_suffix(self.quality_switch)
            self.quality_row.set_activatable_widget(self.quality_switch)
            group.add(self.quality_row)

            return group

        def _build_account_group(self) -> Adw.PreferencesGroup:
            group = Adw.PreferencesGroup(
                title="Account",
                description="Sign in once, or paste a token to download right away.",
            )

            self.account_row = Adw.ActionRow(
                title="Authentication", subtitle="Checking…"
            )
            self.account_icon = Gtk.Image.new_from_icon_name(
                "content-loading-symbolic"
            )
            self.account_row.add_prefix(self.account_icon)
            self.auth_button = Gtk.Button(
                label="Authenticate", valign=Gtk.Align.CENTER
            )
            self.auth_button.add_css_class("suggested-action")
            self.auth_button.connect("clicked", self._on_authenticate_clicked)
            self.account_row.add_suffix(self.auth_button)
            group.add(self.account_row)

            self.token_row = Adw.PasswordEntryRow(title="Token override (optional)")
            self.token_row.connect("changed", lambda *_: self._update_gate())
            group.add(self.token_row)

            return group

        def _build_progress_group(self) -> Adw.PreferencesGroup:
            group = Adw.PreferencesGroup(title="Activity")

            box = Gtk.Box(
                orientation=Gtk.Orientation.VERTICAL,
                spacing=8,
                margin_top=6,
                margin_bottom=6,
                margin_start=6,
                margin_end=6,
            )

            self.status_label = Gtk.Label(label="Ready", xalign=0.0, wrap=True)
            self.status_label.add_css_class("dim-label")
            box.append(self.status_label)

            self.progress_bar = Gtk.ProgressBar(show_text=False)
            self.progress_bar.set_visible(False)
            box.append(self.progress_bar)

            group.add(box)

            self.log_expander = Adw.ExpanderRow(
                title="Log", subtitle="Detailed progress messages"
            )
            clear_button = Gtk.Button(
                icon_name="edit-clear-all-symbolic",
                valign=Gtk.Align.CENTER,
                tooltip_text="Clear log",
            )
            clear_button.add_css_class("flat")
            clear_button.connect("clicked", lambda *_: self._clear_log())
            self.log_expander.add_suffix(clear_button)

            self.log_view = Gtk.TextView(
                editable=False,
                cursor_visible=False,
                monospace=True,
                top_margin=8,
                bottom_margin=8,
                left_margin=8,
                right_margin=8,
                wrap_mode=Gtk.WrapMode.WORD_CHAR,
            )
            self.log_buffer = self.log_view.get_buffer()
            log_scroller = Gtk.ScrolledWindow(
                min_content_height=160,
                max_content_height=260,
                propagate_natural_height=True,
            )
            log_scroller.add_css_class("card")
            log_scroller.set_child(self.log_view)

            log_holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            log_holder.append(log_scroller)
            self.log_expander.add_row(log_holder)
            group.add(self.log_expander)

            return group

        # ------------------------------------------------------------- helpers

        def _toast(self, message: str) -> None:
            self.toasts.add_toast(Adw.Toast(title=message, timeout=4))

        def _append_log(self, message: str) -> None:
            end = self.log_buffer.get_end_iter()
            prefix = "" if self.log_buffer.get_char_count() == 0 else "\n"
            self.log_buffer.insert(end, prefix + message)
            mark = self.log_buffer.get_insert()
            self.log_view.scroll_mark_onscreen(mark)

        def _clear_log(self) -> None:
            self.log_buffer.set_text("")

        def _set_status(self, text: str) -> None:
            self.status_label.set_text(text)

        def _refresh_storage_status(self) -> None:
            subtitle, has_token, icon = self._storage_status()
            self._has_stored_token = has_token
            self._base_account_subtitle = subtitle
            self._base_account_icon = icon
            self._update_gate()

        def _storage_status(self) -> tuple[str, bool, str]:
            try:
                saved = get_saved_auth_token()
            except AuthError:
                return (
                    "Token unavailable — check your keyring",
                    False,
                    "dialog-warning-symbolic",
                )
            if saved:
                return "Authorized", True, "emblem-ok-symbolic"
            if keyring_is_available():
                return "Not authorized", False, "dialog-password-symbolic"
            return "Using environment token only", False, "dialog-password-symbolic"

        def _authorized(self) -> bool:
            """Authorized means a saved/env token exists or one was pasted."""
            return self._has_stored_token or bool(self.token_row.get_text().strip())

        def _update_gate(self) -> None:
            """Gate the whole app behind authentication.

            The Source and Options groups (and the Download action) stay
            disabled until the user signs in or pastes a token. The Account
            group is always reachable so authentication remains possible.
            """
            has_override = bool(self.token_row.get_text().strip())
            authorized = self._has_stored_token or has_override

            if self._has_stored_token:
                subtitle, icon = self._base_account_subtitle, self._base_account_icon
            elif has_override:
                subtitle, icon = "Using token override", "emblem-ok-symbolic"
            else:
                subtitle, icon = self._base_account_subtitle, self._base_account_icon
            self.account_row.set_subtitle(subtitle)
            self.account_icon.set_from_icon_name(icon)

            self.banner.set_revealed(not authorized)

            enabled = authorized and not self.busy
            self.source_group.set_sensitive(enabled)
            self.options_group.set_sensitive(enabled)
            self._update_actions()

        def _set_busy(self, busy: bool) -> None:
            self.busy = busy
            self.token_row.set_sensitive(not busy)
            self.auth_button.set_sensitive(not busy)
            self.banner.set_sensitive(not busy)
            self._update_gate()

        def _update_actions(self) -> None:
            can_download = (
                not self.busy
                and self.parsed_command is not None
                and self._authorized()
            )
            self.download_button.set_sensitive(can_download)
            is_audiobook = self.parsed_command == "audiobook"
            self.quality_row.set_sensitive(not self.busy and is_audiobook)
            if not is_audiobook:
                self.quality_switch.set_active(False)

        # --------------------------------------------------------- URL parsing

        def _update_url_details(self) -> None:
            raw = self.url_row.get_text().strip()
            if not raw:
                self.parsed_command = None
                self.parsed_uuid = None
                self.detected_row.set_subtitle("Waiting for a URL")
                self.detected_icon.set_from_icon_name("content-loading-symbolic")
                self.url_row.remove_css_class("error")
                self._update_actions()
                return

            try:
                command, uuid = parse_resource_url(raw)
            except ValueError as exc:
                self.parsed_command = None
                self.parsed_uuid = None
                self.detected_row.set_subtitle(str(exc))
                self.detected_icon.set_from_icon_name("dialog-warning-symbolic")
                self.url_row.add_css_class("error")
                self._update_actions()
                return

            self.parsed_command = command
            self.parsed_uuid = uuid
            self.detected_row.set_subtitle(f"{COMMAND_LABELS[command]} · {uuid}")
            self.detected_icon.set_from_icon_name("emblem-ok-symbolic")
            self.url_row.remove_css_class("error")
            self._update_actions()

        # ------------------------------------------------------- folder picker

        def _on_choose_folder(self, _button: Gtk.Button) -> None:
            if hasattr(Gtk, "FileDialog"):
                dialog = Gtk.FileDialog(title="Choose download folder")
                try:
                    dialog.set_initial_folder(
                        Gio.File.new_for_path(str(self.output_dir.parent))
                    )
                except Exception:  # pragma: no cover - non-fatal
                    pass
                dialog.select_folder(self, None, self._on_folder_selected)
            else:  # pragma: no cover - legacy GTK fallback
                chooser = Gtk.FileChooserNative(
                    title="Choose download folder",
                    transient_for=self,
                    action=Gtk.FileChooserAction.SELECT_FOLDER,
                )
                chooser.connect("response", self._on_native_folder_response)
                chooser.show()

        def _on_folder_selected(self, dialog: Gtk.FileDialog, result) -> None:
            try:
                folder = dialog.select_folder_finish(result)
            except GLib.Error:
                return
            if folder is not None and folder.get_path():
                self._apply_folder(Path(folder.get_path()))

        def _on_native_folder_response(  # pragma: no cover - legacy GTK fallback
            self, chooser: Gtk.FileChooserNative, response: int
        ) -> None:
            if response == Gtk.ResponseType.ACCEPT:
                folder = chooser.get_file()
                if folder is not None and folder.get_path():
                    self._apply_folder(Path(folder.get_path()))
            chooser.destroy()

        def _apply_folder(self, folder: Path) -> None:
            if folder.name != "MateLoader":
                folder = folder / "MateLoader"
            self.output_dir = folder
            self.folder_row.set_subtitle(str(self.output_dir))

        # --------------------------------------------------------- auth action

        def _on_authenticate_clicked(self, _button: Gtk.Button) -> None:
            if self.busy:
                return
            self._set_busy(True)
            self._set_status("Authenticating…")
            self._append_log("Opening the Yandex authentication window…")

            thread = threading.Thread(target=self._auth_worker, daemon=True)
            thread.start()

        def _auth_worker(self) -> None:
            command, environment = _auth_subprocess_command()
            try:
                completed = subprocess.run(
                    command,
                    env=environment,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except OSError as exc:
                GLib.idle_add(
                    self._auth_failed, f"Failed to start authentication: {exc}"
                )
                return

            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip()
                GLib.idle_add(self._auth_failed, message or "Authentication failed.")
                return

            GLib.idle_add(self._auth_finished)

        def _auth_finished(self) -> bool:
            self._set_busy(False)
            self.token_row.set_text("")
            self._refresh_storage_status()
            self._set_status("Authenticated")
            self._append_log("Authentication token saved.")
            self._toast("Signed in to Yandex")
            return False

        def _auth_failed(self, message: str) -> bool:
            self._set_busy(False)
            self._set_status("Authentication failed")
            self._append_log(message)
            self._toast("Authentication failed")
            return False

        # ----------------------------------------------------- download action

        def _on_download_clicked(self, _widget) -> None:
            if self.busy or self.parsed_command is None:
                return

            raw = self.url_row.get_text().strip()
            try:
                command, uuid = parse_resource_url(raw)
            except ValueError as exc:
                self._set_status(str(exc))
                self._toast("That URL is not valid")
                return

            try:
                stored = get_saved_auth_token()
            except AuthError as exc:
                self._set_status("Token error")
                self._append_log(str(exc))
                self._toast("Could not read the stored token")
                return

            token = self.token_row.get_text().strip() or stored
            if not token:
                self._set_status("Authenticate first")
                self._append_log(
                    "An authentication token is required before downloading."
                )
                self._toast("Authenticate first")
                return

            self._clear_log()
            self._append_log(f"Starting {command} download for {uuid}")
            self._set_status("Starting…")
            self._set_busy(True)
            self._start_progress()

            thread = threading.Thread(
                target=self._download_worker,
                args=(
                    command,
                    uuid,
                    self.quality_switch.get_active(),
                    token,
                    self.output_dir,
                ),
                daemon=True,
            )
            thread.start()

        def _download_worker(
            self,
            command: str,
            uuid: str,
            max_bitrate: bool,
            token: str,
            output_dir: Path,
        ) -> None:
            def log(message: str) -> None:
                GLib.idle_add(self._append_log, message)

            def progress(current: int, total: int, label: str) -> None:
                GLib.idle_add(self._on_progress, current, total, label)

            try:
                run_download(
                    command,
                    uuid,
                    max_bitrate=max_bitrate,
                    auth_token=token,
                    output_root=output_dir,
                    progress_callback=log,
                    on_progress=progress,
                )
            except (AuthError, DownloaderError) as exc:
                GLib.idle_add(self._download_failed, str(exc))
                return
            except Exception as exc:  # pragma: no cover - defensive UI boundary
                GLib.idle_add(self._download_failed, str(exc))
                return
            GLib.idle_add(self._download_finished)

        # ----------------------------------------------------------- progress

        def _start_progress(self) -> None:
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(0.0)
            self._begin_pulse()

        def _begin_pulse(self) -> None:
            if self._pulse_source is not None:
                return
            self.progress_bar.pulse()
            self._pulse_source = GLib.timeout_add(120, self._pulse_tick)

        def _pulse_tick(self) -> bool:
            self.progress_bar.pulse()
            return True

        def _stop_pulse(self) -> None:
            if self._pulse_source is not None:
                GLib.source_remove(self._pulse_source)
                self._pulse_source = None

        def _on_progress(self, current: int, total: int, label: str) -> bool:
            self._set_status(label)
            if total > 0:
                self._stop_pulse()
                self.progress_bar.set_fraction(max(0.0, min(1.0, current / total)))
            else:
                self._begin_pulse()
            return False

        def _end_progress(self) -> None:
            self._stop_pulse()
            self.progress_bar.set_visible(False)

        def _download_finished(self) -> bool:
            self._end_progress()
            self._set_busy(False)
            self._refresh_storage_status()
            self._set_status("Download complete")
            self._append_log("Download completed.")
            self._toast("Download complete")
            return False

        def _download_failed(self, message: str) -> bool:
            self._end_progress()
            self._set_busy(False)
            self._refresh_storage_status()
            self._set_status("Download failed")
            self._append_log(message)
            self._toast("Download failed")
            return False

    class MateLoaderApplication(Adw.Application):
        def __init__(self) -> None:
            super().__init__(
                application_id=APP_ID,
                flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
            )
            self.window: MateLoaderWindow | None = None

        def do_startup(self) -> None:
            Adw.Application.do_startup(self)
            about_action = Gio.SimpleAction.new("about", None)
            about_action.connect("activate", self._on_about)
            self.add_action(about_action)

        def do_activate(self) -> None:
            if self.window is None:
                self._register_packaged_icons()
                self.window = MateLoaderWindow(self)
            self.window.present()

        def _register_packaged_icons(self) -> None:
            """Let the app find its own bundled icon without a system install.

            Adds the repository's ``data/icons`` directory to the icon theme
            search path so the MateLoader logo resolves during local
            development. Standard symbolic icons still come from the installed
            Adwaita icon theme.
            """
            display = Gdk.Display.get_default()
            if display is None:
                return
            icons_dir = Path(__file__).resolve().parents[2] / "data" / "icons"
            if icons_dir.is_dir():
                theme = Gtk.IconTheme.get_for_display(display)
                theme.add_search_path(str(icons_dir))

        def _on_about(self, *_args) -> None:
            about_kwargs = dict(
                application_name=APP_NAME,
                application_icon=APP_ID,
                version=_app_version(),
                developer_name="Gago Alaverdyan",
                developers=["Gago Alaverdyan https://github.com/gagoalaverdyan"],
                copyright="© 2026 Gago Alaverdyan",
                comments="Download supported Yandex Books content.",
                license_type=Gtk.License.GPL_3_0,
                website="https://github.com/gagoalaverdyan/MateLoader",
                issue_url="https://github.com/gagoalaverdyan/MateLoader/issues",
            )
            if hasattr(Adw, "AboutDialog"):
                dialog = Adw.AboutDialog(**about_kwargs)
                dialog.present(self.window)
            else:
                dialog = Adw.AboutWindow(transient_for=self.window, **about_kwargs)
                dialog.present()


def main() -> None:
    if GTK_IMPORT_ERROR is not None:
        raise SystemExit(
            "GUI dependencies are not installed. Install `mateloader[gui]` and the "
            "GTK 4 / libadwaita system libraries to use the desktop app.\n"
            f"(import error: {GTK_IMPORT_ERROR})"
        )

    app = MateLoaderApplication()
    sys.exit(app.run(sys.argv))
