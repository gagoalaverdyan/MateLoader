from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .auth import AuthError, get_saved_auth_token, keyring_is_available
from .downloader import DownloaderError, run_download

try:
    from PySide6.QtCore import QObject, QThread, Signal, Slot
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QComboBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover - dependency issue
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


COMMANDS = [
    ("Book", "book"),
    ("Audiobook", "audiobook"),
    ("Comicbook", "comicbook"),
    ("Serial", "serial"),
    ("Series", "series"),
]


if QT_IMPORT_ERROR is None:

    def _auth_subprocess_command() -> tuple[list[str], dict[str, str]]:
        environment = os.environ.copy()
        src_root = str(Path(__file__).resolve().parents[1])
        existing_pythonpath = environment.get("PYTHONPATH", "")
        if existing_pythonpath:
            environment["PYTHONPATH"] = os.pathsep.join((src_root, existing_pythonpath))
        else:
            environment["PYTHONPATH"] = src_root
        return [sys.executable, "-m", "mateloader", "auth"], environment


    class DownloadWorker(QObject):
        finished = Signal()
        failed = Signal(str)
        log = Signal(str)

        def __init__(self, command: str, uuid: str, max_bitrate: bool, token: str):
            super().__init__()
            self.command = command
            self.uuid = uuid
            self.max_bitrate = max_bitrate
            self.token = token

        @Slot()
        def run(self) -> None:
            try:
                run_download(
                    self.command,
                    self.uuid,
                    max_bitrate=self.max_bitrate,
                    auth_token=self.token,
                    progress_callback=self.log.emit,
                )
            except (AuthError, DownloaderError) as exc:
                self.failed.emit(str(exc))
                return
            except Exception as exc:  # pragma: no cover - defensive UI boundary
                self.failed.emit(str(exc))
                return
            self.finished.emit()


    class AuthWorker(QObject):
        finished = Signal()
        failed = Signal(str)

        @Slot()
        def run(self) -> None:
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
                self.failed.emit(f"Failed to start authentication: {exc}")
                return

            if completed.returncode != 0:
                message = completed.stderr.strip() or completed.stdout.strip()
                self.failed.emit(message or "Authentication failed.")
                return

            self.finished.emit()


    class MateLoaderWindow(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.thread: QThread | None = None
            self.worker: DownloadWorker | None = None
            self.auth_thread: QThread | None = None
            self.auth_worker: AuthWorker | None = None

            self.command_combo = QComboBox()
            for label, value in COMMANDS:
                self.command_combo.addItem(label, value)

            self.uuid_input = QLineEdit()
            self.uuid_input.setPlaceholderText("Resource ID")

            self.max_bitrate_checkbox = QCheckBox("Max quality")

            self.token_input = QLineEdit()
            self.token_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
            self.token_input.setPlaceholderText("Optional override token")

            self.auth_button = QPushButton("Authenticate")
            self.start_button = QPushButton("Download")

            self.status_label = QLabel("Idle")
            self.location_label = QLabel(self._storage_text())
            self.location_label.setWordWrap(True)

            self.log_output = QPlainTextEdit()
            self.log_output.setReadOnly(True)

            self._build_ui()
            self._connect_signals()
            self._update_quality_toggle()

        def _storage_text(self) -> str:
            try:
                saved_token = get_saved_auth_token()
            except AuthError:
                return "Token status: unavailable because the saved token could not be read"

            if saved_token:
                return "Token available: stored token will be used when the override field is empty"
            if keyring_is_available():
                return "Token available: none saved yet"
            return "Token storage: environment variables only"

        def _build_ui(self) -> None:
            self.setWindowTitle("MateLoader")
            self.resize(600, 440)

            form = QFormLayout()
            form.addRow("Type", self.command_combo)
            form.addRow("ID", self.uuid_input)
            form.addRow("", self.max_bitrate_checkbox)
            form.addRow("Token", self.token_input)

            buttons = QHBoxLayout()
            buttons.addWidget(self.auth_button)
            buttons.addWidget(self.start_button)

            layout = QVBoxLayout()
            layout.setContentsMargins(18, 18, 18, 18)
            layout.setSpacing(12)
            layout.addLayout(form)
            layout.addLayout(buttons)
            layout.addWidget(self.location_label)
            layout.addWidget(self.status_label)
            layout.addWidget(self.log_output)
            self.setLayout(layout)

        def _connect_signals(self) -> None:
            self.command_combo.currentIndexChanged.connect(self._update_quality_toggle)
            self.auth_button.clicked.connect(self.authenticate)
            self.start_button.clicked.connect(self.start_download)

        def _set_running(self, running: bool) -> None:
            self.command_combo.setDisabled(running)
            self.uuid_input.setDisabled(running)
            self.max_bitrate_checkbox.setDisabled(
                running or self.command_combo.currentData() != "audiobook"
            )
            self.token_input.setDisabled(running)
            self.auth_button.setDisabled(running)
            self.start_button.setDisabled(running)

        def _append_log(self, message: str) -> None:
            self.log_output.appendPlainText(message)

        @Slot()
        def _update_quality_toggle(self) -> None:
            is_audiobook = self.command_combo.currentData() == "audiobook"
            self.max_bitrate_checkbox.setEnabled(is_audiobook and self.thread is None)
            if not is_audiobook:
                self.max_bitrate_checkbox.setChecked(False)

        @Slot()
        def authenticate(self) -> None:
            self.status_label.setText("Authenticating...")
            self._append_log("Opening the Yandex authentication window...")
            self._set_running(True)

            self.auth_thread = QThread(self)
            self.auth_worker = AuthWorker()
            self.auth_worker.moveToThread(self.auth_thread)

            self.auth_thread.started.connect(self.auth_worker.run)
            self.auth_worker.finished.connect(self.on_auth_finished)
            self.auth_worker.failed.connect(self.on_auth_failed)

            self.auth_worker.finished.connect(self.auth_thread.quit)
            self.auth_worker.failed.connect(self.auth_thread.quit)
            self.auth_worker.finished.connect(self.auth_worker.deleteLater)
            self.auth_worker.failed.connect(self.auth_worker.deleteLater)
            self.auth_thread.finished.connect(self.auth_thread.deleteLater)
            self.auth_thread.finished.connect(self._cleanup_auth_thread)

            self.auth_thread.start()

        @Slot()
        def start_download(self) -> None:
            uuid = self.uuid_input.text().strip()
            if not uuid:
                self.status_label.setText("Enter a resource ID")
                return

            try:
                stored_token = get_saved_auth_token()
            except AuthError as exc:
                self.status_label.setText("Authentication failed")
                self._append_log(str(exc))
                return

            token = self.token_input.text().strip() or stored_token
            if not token:
                self.status_label.setText("Authenticate first")
                self._append_log(
                    "Authentication token is required before starting a download"
                )
                return

            self.log_output.clear()
            self.status_label.setText("Downloading...")
            self._append_log(
                f"Starting {self.command_combo.currentData()} download for {uuid}"
            )
            self._set_running(True)

            self.thread = QThread(self)
            self.worker = DownloadWorker(
                self.command_combo.currentData(),
                uuid,
                self.max_bitrate_checkbox.isChecked(),
                token,
            )
            self.worker.moveToThread(self.thread)

            self.thread.started.connect(self.worker.run)
            self.worker.log.connect(self._append_log)
            self.worker.finished.connect(self.on_download_finished)
            self.worker.failed.connect(self.on_download_failed)

            self.worker.finished.connect(self.thread.quit)
            self.worker.failed.connect(self.thread.quit)
            self.worker.finished.connect(self.worker.deleteLater)
            self.worker.failed.connect(self.worker.deleteLater)
            self.thread.finished.connect(self.thread.deleteLater)
            self.thread.finished.connect(self._cleanup_thread)

            self.thread.start()

        @Slot()
        def on_download_finished(self) -> None:
            self.status_label.setText("Done")
            self._append_log("Download completed")

        @Slot(str)
        def on_download_failed(self, message: str) -> None:
            self.status_label.setText("Failed")
            self._append_log(message)

        @Slot()
        def on_auth_finished(self) -> None:
            self.token_input.clear()
            self.location_label.setText(self._storage_text())
            self.status_label.setText("Authenticated")
            self._append_log("Authentication token saved")

        @Slot(str)
        def on_auth_failed(self, message: str) -> None:
            self.status_label.setText("Authentication failed")
            self._append_log(message)

        @Slot()
        def _cleanup_thread(self) -> None:
            self.thread = None
            self.worker = None
            self._refresh_running_state()

        @Slot()
        def _cleanup_auth_thread(self) -> None:
            self.auth_thread = None
            self.auth_worker = None
            self._refresh_running_state()

        def _refresh_running_state(self) -> None:
            is_busy = self.thread is not None or self.auth_thread is not None
            self._set_running(is_busy)
            self._update_quality_toggle()
            self.location_label.setText(self._storage_text())


def main() -> None:
    if QT_IMPORT_ERROR is not None:
        raise SystemExit(
            "GUI dependencies are not installed. Install `mateloader[gui]` to use the desktop app."
        )

    app = QApplication(sys.argv)
    window = MateLoaderWindow()
    window.show()
    sys.exit(app.exec())
