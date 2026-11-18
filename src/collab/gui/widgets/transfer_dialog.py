"""Incoming file offer dialog with a live countdown."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .formatting import human_size, sanitize


class TransferOfferDialog(QDialog):
    accepted_transfer = Signal(str)
    rejected_transfer = Signal(str, str)

    def __init__(self, offer: dict, parent=None) -> None:
        super().__init__(parent)
        self.offer = offer
        self.transfer_id = str(offer.get("transfer_id", ""))
        self._remaining = int(offer.get("expires_in_sec", 60) or 60)
        self._decided = False
        self.setWindowTitle("Có tệp gửi tới")
        self.setMinimumWidth(420)

        size = int(offer.get("size", 0) or 0)
        chunks = offer.get("total_chunks", "?")
        info = QLabel(
            f"{sanitize(offer.get('from'))} muốn gửi cho bạn một tệp:\n\n"
            f"Tên tệp: {sanitize(offer.get('filename'))}\nKích thước: {human_size(size)} ({chunks} chunk)\n"
            f"Mã giao dịch: {self.transfer_id[:8]}"
        )
        info.setTextFormat(Qt.TextFormat.PlainText)
        info.setWordWrap(True)
        self._countdown = QLabel("")
        self._countdown.setObjectName("hint")
        self._btn_accept = QPushButton("Chấp nhận")
        self._btn_accept.setObjectName("primary")
        self._btn_reject = QPushButton("Từ chối")
        self._btn_accept.clicked.connect(self._accept)
        self._btn_reject.clicked.connect(self._reject)

        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(self._btn_reject)
        row.addWidget(self._btn_accept)
        lay = QVBoxLayout(self)
        lay.addWidget(info)
        lay.addWidget(self._countdown)
        lay.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(lambda: self.tick(1))
        self._render()

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def tick(self, seconds: int) -> None:
        if self._decided:
            return
        self._remaining -= seconds
        if self._remaining <= 0:
            self.set_expired()
        else:
            self._render()

    def _render(self) -> None:
        self._countdown.setText(f"Lời mời hết hạn sau {max(self._remaining, 0)} giây")

    def set_expired(self, text: str = "Lời mời đã hết hạn hoặc bị người gửi hủy.") -> None:
        self._decided = True
        self._timer.stop()
        self._countdown.setText(text)
        self._btn_accept.setEnabled(False)
        self._btn_reject.setText("Đóng")
        self._btn_reject.clicked.disconnect()
        self._btn_reject.clicked.connect(self.close)

    def _accept(self) -> None:
        self._decided = True
        self._timer.stop()
        self.accepted_transfer.emit(self.transfer_id)
        self.accept()

    def _reject(self) -> None:
        self._decided = True
        self._timer.stop()
        self.rejected_transfer.emit(self.transfer_id, "rejected_by_user")
        self.reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._decided:
            self._decided = True
            self.rejected_transfer.emit(self.transfer_id, "dismissed")
        self._timer.stop()
        super().closeEvent(event)

