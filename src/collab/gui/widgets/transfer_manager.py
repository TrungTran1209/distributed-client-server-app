"""Transfer Center panel: outgoing and incoming transfers."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from .transfer_item import TransferItemWidget


class TransferManagerWidget(QWidget):
    cancel_requested = Signal(str)
    download_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._items: dict[str, TransferItemWidget] = {}
        self._item_conversations: dict[str, str | None] = {}
        self._conversation: str | None = None
        self._out_box, self._out_lay = self._section("Đã gửi")
        self._in_box, self._in_lay = self._section("Đã nhận")
        self._empty = QLabel("Chưa có tệp trong cuộc trò chuyện này.")
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
        item.download_requested.connect(self.download_requested)
        self._items[item.transfer_id] = item
        lay.addWidget(item)
        box.show()
        self._empty.hide()

    def set_conversation(self, conversation: str | None) -> None:
        self._conversation = conversation
        visible = False
        for tid, item in self._items.items():
            item.setVisible(self._item_conversations.get(tid) == conversation)
            visible = visible or item.isVisible()
        self._empty.setVisible(not visible)
        self._out_box.setVisible(
            any(
                True
                for tid, item in self._items.items()
                if self._item_conversations.get(tid) == conversation
                and item.direction == "send"
            )
        )
        self._in_box.setVisible(
            any(
                self._item_conversations.get(tid) == conversation
                and item.direction == "receive"
                for tid, item in self._items.items()
            )
        )

    def add_outgoing(self, transfer_id: str, filename: str, recipient: str, conversation: str | None = None) -> None:
        if transfer_id not in self._items:
            self._item_conversations[transfer_id] = recipient if conversation is None else conversation
            self._add(TransferItemWidget(transfer_id, filename, recipient, "send"), self._out_box, self._out_lay)
            self.set_conversation(self._conversation)

    def add_incoming(self, transfer_id: str, filename: str, sender: str, conversation: str | None = None) -> None:
        item = self._items.get(transfer_id)
        if item is not None:
            item.mark_started()
            return
        self._item_conversations[transfer_id] = sender if conversation is None else conversation
        self._add(TransferItemWidget(transfer_id, filename, sender, "receive"), self._in_box, self._in_lay)
        self.set_conversation(self._conversation)

    def add_incoming_offer(
        self,
        transfer_id: str,
        filename: str,
        sender: str,
        conversation: str | None = None,
    ) -> None:
        if transfer_id not in self._items:
            self._item_conversations[transfer_id] = sender if conversation is None else conversation
            self._add(
                TransferItemWidget(
                    transfer_id,
                    filename,
                    sender,
                    "receive",
                    pending=True,
                ),
                self._in_box,
                self._in_lay,
            )
            self.set_conversation(self._conversation)

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
