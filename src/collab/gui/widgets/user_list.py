"""Sidebar directory widget displaying separate Online and Offline user tables plus Broadcast."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .formatting import sanitize

BROADCAST_LABEL = "📢 Kênh chung (Tất cả mọi người)"
_USER_ROLE = Qt.ItemDataRole.UserRole


@dataclass(frozen=True)
class _LogicalItem:
    _text: str

    def text(self) -> str:
        return self._text


def _make_user_table(second_header: str) -> QTableWidget:
    table = QTableWidget(0, 2)
    table.setHorizontalHeaderLabels(["Tài khoản", second_header])
    table.verticalHeader().setVisible(False)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setShowGrid(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
    header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
    return table


class UserListWidget(QWidget):
    """Displays Broadcast button + dedicated Online Users table + Offline Users table."""

    recipient_changed = Signal(object)  # None (broadcast) or username str

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._own: str | None = None
        self._selected: str | None = None
        self._online: list[dict] = []
        self._offline: list[dict] = []
        self._unread: dict[str | None, int] = {}
        self._logical_items: list[_LogicalItem] = [_LogicalItem(BROADCAST_LABEL)]

        self._btn_broadcast = QPushButton(BROADCAST_LABEL)
        self._btn_broadcast.setCheckable(True)
        self._btn_broadcast.setChecked(True)
        self._btn_broadcast.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_broadcast.clicked.connect(lambda: self.select_user(None))

        self._online_header = QLabel("🟢 TRỰC TUYẾN (0)")
        self._online_header.setStyleSheet("color: #059669; font-weight: 800; font-size: 12px; padding-top: 6px;")
        self._online_table = _make_user_table("Kết nối")
        self._online_table.itemSelectionChanged.connect(self._on_online_table_selected)

        self._offline_header = QLabel("⚪ NGOẠI TUYẾN (0)")
        self._offline_header.setStyleSheet("color: #64748B; font-weight: 800; font-size: 12px; padding-top: 6px;")
        self._offline_table = _make_user_table("Trạng thái")
        self._offline_table.itemSelectionChanged.connect(self._on_offline_table_selected)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._btn_broadcast)
        layout.addWidget(self._online_header)
        layout.addWidget(self._online_table, 3)
        layout.addWidget(self._offline_header)
        layout.addWidget(self._offline_table, 2)
        self._apply_broadcast_style()

    def _apply_broadcast_style(self) -> None:
        active = self._selected is None
        unread = self._unread.get(None, 0)
        suffix = f"  ({unread} mới)" if unread else ""
        self._btn_broadcast.setText(BROADCAST_LABEL + suffix)
        self._btn_broadcast.setChecked(active)
        if active:
            self._btn_broadcast.setStyleSheet(
                "QPushButton { background: #4F46E5; color: #FFFFFF; border: none; "
                "border-radius: 10px; padding: 10px 12px; font-weight: 700; text-align: left; }"
            )
        else:
            self._btn_broadcast.setStyleSheet(
                "QPushButton { background: #EEF2FF; color: #3730A3; border: 1px solid #C7D2FE; "
                "border-radius: 10px; padding: 10px 12px; font-weight: 700; text-align: left; }"
                "QPushButton:hover { background: #E0E7FF; }"
            )

    # ------------------------------------------------------------- queries
    def set_own_username(self, username: str | None) -> None:
        self._own = username

    def usernames(self) -> list[str]:
        return [*self.online_usernames(), *self.offline_usernames()]

    def online_usernames(self) -> list[str]:
        return [str(u["username"]) for u in self._online]

    def offline_usernames(self) -> list[str]:
        return [str(u["username"]) for u in self._offline]

    def count(self) -> int:
        return len(self._logical_items)

    def item(self, index: int) -> _LogicalItem:
        return self._logical_items[index]

    def get_selected_recipient(self) -> str | None:
        return self._selected

    def is_selected_online(self) -> bool:
        if self._selected is None:
            return True
        return self._selected in set(self.online_usernames())

    def is_user_online(self, username: str) -> bool:
        return username in set(self.online_usernames())

    def increment_unread(self, key: str | None) -> None:
        if key == self._selected:
            return
        self._unread[key] = self._unread.get(key, 0) + 1
        self._render_tables(preserve_selection=True, emit_change=False)

    def clear_unread(self, key: str | None) -> None:
        if self._unread.pop(key, 0):
            self._render_tables(preserve_selection=True, emit_change=False)

    # ----------------------------------------------------------- selection
    def select_user(self, username: str | None) -> None:
        previous = self._selected
        if username is not None and username not in set(self.usernames()):
            username = None
        self._selected = username
        self._unread.pop(username, None)
        self._sync_selection_widgets()
        if self._selected != previous:
            self.recipient_changed.emit(self._selected)

    def _on_online_table_selected(self) -> None:
        items = self._online_table.selectedItems()
        if not items:
            return
        uname = items[0].data(_USER_ROLE)
        if isinstance(uname, str):
            self._offline_table.blockSignals(True)
            self._offline_table.clearSelection()
            self._offline_table.blockSignals(False)
            prev = self._selected
            self._selected = uname
            self._unread.pop(uname, None)
            self._apply_broadcast_style()
            if self._selected != prev:
                self.recipient_changed.emit(self._selected)

    def _on_offline_table_selected(self) -> None:
        items = self._offline_table.selectedItems()
        if not items:
            return
        uname = items[0].data(_USER_ROLE)
        if isinstance(uname, str):
            self._online_table.blockSignals(True)
            self._online_table.clearSelection()
            self._online_table.blockSignals(False)
            prev = self._selected
            self._selected = uname
            self._unread.pop(uname, None)
            self._apply_broadcast_style()
            if self._selected != prev:
                self.recipient_changed.emit(self._selected)

    def _sync_selection_widgets(self) -> None:
        self._online_table.blockSignals(True)
        self._offline_table.blockSignals(True)
        self._online_table.clearSelection()
        self._offline_table.clearSelection()
        if self._selected is not None:
            for table in (self._online_table, self._offline_table):
                for row in range(table.rowCount()):
                    cell = table.item(row, 0)
                    if cell is not None and cell.data(_USER_ROLE) == self._selected:
                        table.selectRow(row)
                        break
        self._online_table.blockSignals(False)
        self._offline_table.blockSignals(False)
        self._apply_broadcast_style()

    # ------------------------------------------------------------- updates
    def set_users(self, users: list[dict]) -> None:
        """Backward-compatible setter when only online users are supplied."""
        entries = []
        for u in users:
            if isinstance(u, dict) and u.get("username"):
                entries.append(
                    {
                        "username": u.get("username"),
                        "online": bool(u.get("online", True)),
                        "host": u.get("host"),
                        "port": u.get("port"),
                    }
                )
        self.set_directory(entries)

    def set_directory(self, directory: list[dict]) -> None:
        """Populate both Online and Offline user tables from directory entries."""
        previous = self._selected
        online_rows: list[dict] = []
        offline_rows: list[dict] = []
        for raw in directory:
            if not isinstance(raw, dict):
                continue
            name = sanitize(raw.get("username"))
            if not name or name == self._own:
                continue
            item = {
                "username": name,
                "online": bool(raw.get("online", True)),
                "host": raw.get("host"),
                "port": raw.get("port"),
            }
            if item["online"]:
                online_rows.append(item)
            else:
                offline_rows.append(item)

        self._online = online_rows
        self._offline = offline_rows
        all_known = {u["username"] for u in online_rows} | {u["username"] for u in offline_rows}
        if self._selected is not None and self._selected not in all_known:
            self._selected = None

        self._render_tables(preserve_selection=True, emit_change=self._selected != previous)

    def _render_tables(self, *, preserve_selection: bool, emit_change: bool) -> None:
        self._online_header.setText(f"🟢 TRỰC TUYẾN ({len(self._online)})")
        self._offline_header.setText(f"⚪ NGOẠI TUYẾN ({len(self._offline)})")
        self._logical_items = [_LogicalItem(BROADCAST_LABEL)]

        self._online_table.blockSignals(True)
        self._online_table.setRowCount(len(self._online))
        for row, u in enumerate(self._online):
            uname = str(u["username"])
            unread = self._unread.get(uname, 0)
            label = f"● {uname}" + (f" ({unread})" if unread else "")
            host, port = u.get("host"), u.get("port")
            detail = f"{sanitize(host)}:{port}" if host and port else "Đang online"
            name_item = QTableWidgetItem(label)
            name_item.setData(_USER_ROLE, uname)
            name_item.setForeground(QColor("#047857"))
            detail_item = QTableWidgetItem(detail)
            detail_item.setData(_USER_ROLE, uname)
            detail_item.setForeground(QColor("#64748B"))
            self._online_table.setItem(row, 0, name_item)
            self._online_table.setItem(row, 1, detail_item)
            self._logical_items.append(_LogicalItem(f"{uname} · {detail}" if host and port else uname))
        self._online_table.blockSignals(False)

        self._offline_table.blockSignals(True)
        self._offline_table.setRowCount(len(self._offline))
        for row, u in enumerate(self._offline):
            uname = str(u["username"])
            unread = self._unread.get(uname, 0)
            label = f"○ {uname}" + (f" ({unread})" if unread else "")
            name_item = QTableWidgetItem(label)
            name_item.setData(_USER_ROLE, uname)
            name_item.setForeground(QColor("#475569"))
            status_item = QTableWidgetItem("Ngoại tuyến")
            status_item.setData(_USER_ROLE, uname)
            status_item.setForeground(QColor("#94A3B8"))
            self._offline_table.setItem(row, 0, name_item)
            self._offline_table.setItem(row, 1, status_item)
            self._logical_items.append(_LogicalItem(f"{uname} (ngoại tuyến)"))
        self._offline_table.blockSignals(False)

        if preserve_selection:
            self._sync_selection_widgets()
        if emit_change:
            self.recipient_changed.emit(self._selected)
