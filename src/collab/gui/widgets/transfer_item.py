"""One row in the Transfer Center. Progress is driven only by real FileSender/FileReceiver callbacks."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .formatting import describe_transfer_error, human_size, sanitize


class TransferItemWidget(QWidget):
    cancel_requested = Signal(str)

    def __init__(self, transfer_id: str, filename: str, peer: str, direction: str, parent=None) -> None:
        super().__init__(parent)
        self.transfer_id, self.direction = transfer_id, direction
        self._finished = False
        self._path: str | None = None
        arrow = "Gửi tới" if direction == "send" else "Nhận từ"
        self._title = QLabel(f"{sanitize(filename)}   ·   {arrow} {sanitize(peer) or '…'}")
        self._title.setStyleSheet("font-weight: 600;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bytes = QLabel("")
        self._bytes.setObjectName("hint")
        self._status = QLabel(
            "Đang chờ người nhận chấp nhận…" if direction == "send" else "Đang chờ bắt đầu nhận…"
        )
        self._btn_cancel = QPushButton("Hủy")
        self._btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.transfer_id))
        self._btn_open = QPushButton("Mở thư mục")
        self._btn_open.clicked.connect(self._open_folder)
        self._btn_open.hide()

        foot = QHBoxLayout()
        foot.addWidget(self._status, 1)
        foot.addWidget(self._bytes)
        foot.addWidget(self._btn_open)
        foot.addWidget(self._btn_cancel)
        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._bar)
        layout.addLayout(foot)

    # ----------------------------------------------------------------- API
    def update_progress(self, progress) -> None:
        if self._finished:
            return
        self._bar.setValue(int(progress.percent))
        self._bytes.setText(f"{human_size(progress.bytes_done)} / {human_size(progress.total_bytes)}")
        if progress.total_chunks and progress.chunks_done >= progress.total_chunks:
            self._status.setText("Đang xác minh SHA-256…")
        else:
            self._status.setText(
                f"Đang gửi… chunk {progress.chunks_done}/{progress.total_chunks}"
                if self.direction == "send"
                else f"Đang nhận… chunk {progress.chunks_done}/{progress.total_chunks}"
            )

    def set_status(self, text: str, error: bool = False) -> None:
        self._status.setText(text)
        self._status.setStyleSheet("color: #f38ba8;" if error else "")

    def set_done(self, ok: bool, path: str | None = None, code: str | None = None) -> None:
        self._finished = True
        self._btn_cancel.hide()
        if ok:
            self._bar.setValue(100)
            self.set_status("Hoàn tất — đã xác minh SHA-256" + (f"\n{path}" if path else ""))
            self._status.setStyleSheet("color: #a6e3a1;")
            if path:
                self._path = path
                self._btn_open.show()
        else:
            self.set_status("Thất bại: " + describe_transfer_error(code), error=True)

    def is_finished(self) -> bool:
        return self._finished

    def progress_value(self) -> int:
        return self._bar.value()

    def bytes_text(self) -> str:
        return self._bytes.text()

    def status_text(self) -> str:
        return self._status.text()

    def _open_folder(self) -> None:
        if self._path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._path).parent)))
