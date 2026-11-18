"""Transfer Center panel: outgoing and incoming transfers."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from .transfer_item import TransferItemWidget


class TransferManagerWidget(QWidget):
    cancel_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: dict[str, TransferItemWidget] = {}
        self._out_box, self._out_lay = self._section("Đang gửi")
        self._in_box, self._in_lay = self._section("Đang nhận")
        self._empty = QLabel("Chưa có truyền tệp nào trong phiên này.")
        self._empty.setObjectName("hint")
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.addWidget(self._empty)
        lay.addWidget(self._out_box)
        lay.addWidget(self._in_box)
        lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    @staticmethod
    def _section(title: str):
        box = QGroupBox(title)
        lay = QVBoxLayout(box)
        box.hide()
        return box, lay

    def _add(self, item: TransferItemWidget, box: QGroupBox, lay: QVBoxLayout) -> None:
        item.cancel_requested.connect(self.cancel_requested)
        self._items[item.transfer_id] = item
        lay.addWidget(item)
        box.show()
        self._empty.hide()

    def add_outgoing(self, transfer_id: str, filename: str, recipient: str) -> None:
        if transfer_id not in self._items:
            self._add(TransferItemWidget(transfer_id, filename, recipient, "send"), self._out_box, self._out_lay)

    def add_incoming(self, transfer_id: str, filename: str, sender: str) -> None:
        if transfer_id not in self._items:
            self._add(TransferItemWidget(transfer_id, filename, sender, "receive"), self._in_box, self._in_lay)

    def update_progress(self, transfer_id: str, progress) -> None:
        item = self._items.get(transfer_id)
        if item is not None:
            item.update_progress(progress)

    def set_transfer_done(self, transfer_id: str, ok: bool, detail: dict) -> None:
        item = self._items.get(transfer_id)
        if item is not None and not item.is_finished():
            item.set_done(ok, detail.get("path"), detail.get("code") or detail.get("message"))

    def has_transfer(self, transfer_id: str) -> bool:
        return transfer_id in self._items

    def active_count(self) -> int:
        return sum(1 for item in self._items.values() if not item.is_finished())
