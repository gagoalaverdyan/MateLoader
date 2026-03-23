from __future__ import annotations

import sys

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

from .auth import AuthError, get_auth_token, keyring_is_available, read_saved_token
from .downloader import DownloaderError, run_download

COMMANDS = [
    ("Book", "book"),
    ("Audiobook", "audiobook"),
    ("Comicbook", "comicbook"),
    ("Serial", "serial"),
    ("Series", "series"),
]


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


class MateLoaderWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.thread: QThread | None = None
        self.worker: DownloadWorker | None = None

        self.command_combo = QComboBox()
        for label, value in COMMANDS:
            self.command_combo.addItem(label, value)

        self.uuid_input = QLineEdit()
        self.uuid_input.setPlaceholderText("Resource ID")

        self.max_bitrate_checkbox = QCheckBox("Max quality")

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Stored token will be used if left empty")
        self.token_input.setText(read_saved_token() or "")

        self.auth_button = QPushButton("Authenticate")
        self.start_button = QPushButton("Download")

        self.status_label = QLabel("Idle")
        storage_text = "Token storage: system keyring" if keyring_is_available() else "Token storage: environment only"
        self.location_label = QLabel(storage_text)
        self.location_label.setWordWrap(True)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)

        self._build_ui()
        self._connect_signals()
        self._update_quality_toggle()

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
        try:
            token = get_auth_token()
        except AuthError as exc:
            self.status_label.setText("Authentication failed")
            self._append_log(str(exc))
            return

        self.token_input.setText(token)
        self.location_label.setText("Token storage: system keyring")
        self.status_label.setText("Authenticated")
        self._append_log("Authentication token saved")

    @Slot()
    def start_download(self) -> None:
        uuid = self.uuid_input.text().strip()
        if not uuid:
            self.status_label.setText("Enter a resource ID")
            return

        token = self.token_input.text().strip() or read_saved_token()
        if not token:
            self.status_label.setText("Authenticate first")
            self._append_log("Authentication token is required before starting a download")
            return

        self.log_output.clear()
        self.status_label.setText("Downloading...")
        self._append_log(f"Starting {self.command_combo.currentData()} download for {uuid}")
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
    def _cleanup_thread(self) -> None:
        self.thread = None
        self.worker = None
        self._set_running(False)
        self._update_quality_toggle()


def main() -> None:
    app = QApplication(sys.argv)
    window = MateLoaderWindow()
    window.show()
    sys.exit(app.exec())
