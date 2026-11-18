"""Online-user list with a permanent broadcast entry."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from .formatting import sanitize

_ROLE = Qt.ItemDataRole.UserRole
BROADCAST_LABEL = "Tất cả mọi người (broadcast)"


class UserListWidget(QListWidget):
    recipient_changed = Signal(object)  # None (broadcast) or username

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._own: str | None = None
        self._users: list[str] = []
        self.currentItemChanged.connect(lambda *_: self.recipient_changed.emit(self.get_selected_recipient()))
        self.set_users([])

    def set_own_username(self, username: str | None) -> None:
        self._own = username

    def usernames(self) -> list[str]:
        return list(self._users)

    def get_selected_recipient(self) -> str | None:
        item = self.currentItem()
        return None if item is None else item.data(_ROLE)

    def select_user(self, username: str | None) -> None:
        for row in range(self.count()):
            if self.item(row).data(_ROLE) == username:
                self.setCurrentRow(row)
                return

    def set_users(self, users: list[dict]) -> None:
        previous = self.get_selected_recipient()
        self.blockSignals(True)
        self.clear()
        head = QListWidgetItem(BROADCAST_LABEL)
        head.setData(_ROLE, None)
        self.addItem(head)
        self._users = []
        for user in users:
            name = sanitize(user.get("username"))
            if not name or name == self._own:
                continue
            self._users.append(name)
            host, port = user.get("host"), user.get("port")
            # presence events carry no address: show only what the server actually told us
            label = f"{name}  ·  {sanitize(host)}:{port}" if host and port else name
            item = QListWidgetItem(label)
            item.setData(_ROLE, name)
            self.addItem(item)
        target = previous if previous in self._users else None
        for row in range(self.count()):
            if self.item(row).data(_ROLE) == target:
                self.setCurrentRow(row)
        self.blockSignals(False)
        if self.get_selected_recipient() != previous:
            self.recipient_changed.emit(self.get_selected_recipient())
