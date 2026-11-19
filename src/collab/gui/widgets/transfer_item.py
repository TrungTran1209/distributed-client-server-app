"""One row in the Transfer Center with modern Figma card styling."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget

from .formatting import describe_transfer_error, human_size, sanitize


class TransferItemWidget(QWidget):
    cancel_requested = Signal(str)
    download_requested = Signal(str)

    def __init__(
        self,
        transfer_id: str,
        filename: str,
        peer: str,
        direction: str,
        parent=None,
        *,
        pending: bool = False,
    ) -> None:
        super().__init__(parent)
        self.transfer_id, self.direction = transfer_id, direction
        self._pending = pending
        self._finished = False
        self._path: str | None = None

        card = QFrame()
        card.setObjectName("card")
        card.setStyleSheet(
            "QFrame#card { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 6px; }"
        )

        icon = "Gửi" if direction == "send" else "Nhận"
        arrow = "Gửi tới" if direction == "send" else "Nhận từ"
        self._title = QLabel(f"{icon}: {sanitize(filename)}   ·   {arrow} {sanitize(peer) or '…'}")
        self._title.setStyleSheet("font-weight: 700; color: #0F172A; font-size: 13px;")

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setStyleSheet("QProgressBar { height: 14px; border-radius: 7px; }")

        self._bytes = QLabel("")
        self._bytes.setObjectName("hint")
        self._status = QLabel(
            "Đang chờ người nhận tải xuống…"
            if direction == "send"
            else "Có tệp mới"
        )
        self._status.setStyleSheet("color: #475569; font-size: 11px;")

        self._btn_cancel = QPushButton("Hủy")
        self._btn_cancel.setStyleSheet(
            "QPushButton { background: #FEE2E2; color: #B91C1C; border: 1px solid #FECACA; "
            "border-radius: 6px; padding: 4px 10px; font-weight: 600; font-size: 11px; }"
            "QPushButton:hover { background: #FCA5A5; }"
        )
        self._btn_cancel.clicked.connect(lambda: self.cancel_requested.emit(self.transfer_id))

        self._btn_download = QPushButton("Tải xuống")
        self._btn_download.clicked.connect(
            lambda: self.download_requested.emit(self.transfer_id)
        )
        self._btn_download.setVisible(direction == "receive" and pending)

        self._btn_open = QPushButton("Mở thư mục")
        self._btn_open.setStyleSheet(
            "QPushButton { background: #EEF2FF; color: #4338CA; border: 1px solid #C7D2FE; "
            "border-radius: 6px; padding: 4px 10px; font-weight: 600; font-size: 11px; }"
            "QPushButton:hover { background: #E0E7FF; }"
        )
        self._btn_open.clicked.connect(self._open_folder)
        self._btn_open.hide()

        foot = QHBoxLayout()
        foot.addWidget(self._status, 1)
        foot.addWidget(self._bytes)
        foot.addWidget(self._btn_download)
        foot.addWidget(self._btn_open)
        foot.addWidget(self._btn_cancel)
        if direction == "receive" and pending:
            self._btn_cancel.hide()

        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(10, 8, 10, 8)
        card_lay.setSpacing(6)
        card_lay.addWidget(self._title)
        card_lay.addWidget(self._bar)
        card_lay.addLayout(foot)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.addWidget(card)

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
        self._status.setStyleSheet("color: #DC2626; font-weight: 700;" if error else "color: #475569;")

    def mark_started(self) -> None:
        self._pending = False
        self._btn_download.hide()
        self._btn_cancel.show()
        self.set_status("Đang tải xuống…")

    def set_done(self, ok: bool, path: str | None = None, code: str | None = None) -> None:
        self._finished = True
        self._btn_cancel.hide()
        if ok:
            self._bar.setValue(100)
            self.set_status("Đã hoàn tất")
            self._status.setStyleSheet("color: #059669; font-weight: 700;")
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
