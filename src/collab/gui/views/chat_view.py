"""Main chat window: user list, message timeline, composer, file button."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..widgets.formatting import sanitize
from ..widgets.message_bubble import MessageBubble
from ..widgets.user_list import UserListWidget

MAX_CHAT_LENGTH = 4000  # mirrors collab.common.protocol.MAX_CHAT_LENGTH


class _Composer(QPlainTextEdit):
    submit = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit.emit()
            return
        super().keyPressEvent(event)


class ChatView(QWidget):
    send_requested = Signal(str, object)
    file_send_requested = Signal(str, object)
    logout_requested = Signal()
    transfers_panel_requested = Signal()
    reconnect_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._username = ""
        self._connected = True
        self._count = 0

        self._server_label = QLabel("")
        self._user_label = QLabel("")
        self._user_label.setStyleSheet("font-weight: 600; color: #89b4fa;")
        self._btn_transfers = QPushButton("Truyền tệp")
        self._btn_transfers.clicked.connect(self.transfers_panel_requested)
        self._btn_logout = QPushButton("Đăng xuất")
        self._btn_logout.clicked.connect(self.logout_requested)
        header = QHBoxLayout()
        header.addWidget(self._server_label)
        header.addStretch()
        header.addWidget(self._user_label)
        header.addWidget(self._btn_transfers)
        header.addWidget(self._btn_logout)

        self._banner = QWidget()
        self._banner.setObjectName("banner")
        self._banner_text = QLabel("")
        self._banner_text.setObjectName("banner")
        self._btn_reconnect = QPushButton("Kết nối lại")
        self._btn_reconnect.clicked.connect(self.reconnect_requested)
        banner_lay = QHBoxLayout(self._banner)
        banner_lay.setContentsMargins(0, 0, 0, 0)
        banner_lay.addWidget(self._banner_text, 1)
        banner_lay.addWidget(self._btn_reconnect)
        self._banner.hide()

        self._users = UserListWidget()
        self._users.setMinimumWidth(200)
        users_title = QLabel("NGƯỜI DÙNG TRỰC TUYẾN")
        users_title.setObjectName("hint")
        self._online_label = QLabel("0 người trực tuyến")
        self._online_label.setObjectName("hint")
        side = QWidget()
        side.setObjectName("sidebar")
        side_lay = QVBoxLayout(side)
        side_lay.addWidget(users_title)
        side_lay.addWidget(self._users, 1)
        side_lay.addWidget(self._online_label)

        self._notice = QLabel("Lịch sử chỉ tồn tại trong phiên này — không được lưu trên server hay ổ đĩa.")
        self._notice.setObjectName("hint")
        self._notice.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._messages = QVBoxLayout()
        self._messages.setAlignment(Qt.AlignmentFlag.AlignTop)
        holder = QWidget()
        holder.setLayout(self._messages)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(holder)

        self._input = _Composer()
        self._input.setPlaceholderText("Nhập tin nhắn… (Enter để gửi, Shift+Enter xuống dòng)")
        self._input.setMaximumHeight(84)
        self._input.submit.connect(self._on_send)
        self._input.textChanged.connect(self._update_counter)
        self._counter = QLabel(f"0/{MAX_CHAT_LENGTH}")
        self._counter.setObjectName("hint")
        self._btn_send = QPushButton("Gửi")
        self._btn_send.setObjectName("primary")
        self._btn_send.clicked.connect(self._on_send)
        self._btn_file = QPushButton("Gửi tệp")
        self._btn_file.clicked.connect(self._on_file)
        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._target_label = QLabel("")
        self._target_label.setObjectName("hint")
        self._users.recipient_changed.connect(self._on_recipient_changed)

        composer = QHBoxLayout()
        composer.addWidget(self._input, 1)
        buttons = QVBoxLayout()
        buttons.addWidget(self._btn_send)
        buttons.addWidget(self._btn_file)
        composer.addLayout(buttons)
        meta = QHBoxLayout()
        meta.addWidget(self._target_label)
        meta.addStretch()
        meta.addWidget(self._counter)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.addWidget(self._notice)
        right_lay.addWidget(self._scroll, 1)
        right_lay.addWidget(self._error_label)
        right_lay.addLayout(meta)
        right_lay.addLayout(composer)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(side)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 760])

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self._banner)
        layout.addWidget(splitter, 1)
        self._on_recipient_changed(None)

    # ------------------------------------------------------------- state
    def set_connection_info(self, host: str, port: int, username: str) -> None:
        self._username = username
        self._users.set_own_username(username)
        self._server_label.setText(f"Máy chủ: {sanitize(host)}:{port}")
        self._user_label.setText(f"Đăng nhập: {sanitize(username)}")

    def set_users(self, users: list[dict]) -> None:
        self._users.set_users(users)
        self._online_label.setText(f"{len(self._users.usernames()) + 1} người trực tuyến (gồm bạn)")

    def show_disconnected_banner(self, reason: str) -> None:
        self._banner_text.setText(f"Mất kết nối: {sanitize(reason)}")
        self._banner.show()
        self._set_enabled(False)

    def hide_disconnected_banner(self) -> None:
        self._banner.hide()
        self._set_enabled(True)

    def _set_enabled(self, enabled: bool) -> None:
        self._connected = enabled
        for widget in (self._input, self._btn_send, self._btn_file):
            widget.setEnabled(enabled)

    def show_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.show()

    def clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()

    def clear_messages(self) -> None:
        while self._messages.count():
            item = self._messages.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._count = 0

    def message_count(self) -> int:
        return self._count

    # ---------------------------------------------------------- messages
    def add_message(self, message: dict) -> None:
        sender = sanitize(message.get("from") or self._username)
        recipient = message.get("to")
        is_own = sender == self._username
        stamp = datetime.datetime.now().strftime("%H:%M")
        bubble = MessageBubble(
            str(message.get("text", "")),
            sender,
            stamp,
            is_own=is_own,
            is_private=recipient is not None,
            private_peer=sanitize(recipient) if is_own and recipient else None,
        )
        self._messages.addWidget(bubble)
        self._count += 1
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(
            self._scroll.verticalScrollBar().maximum()))

    # ----------------------------------------------------------- handlers
    def _on_recipient_changed(self, recipient) -> None:
        self._target_label.setText(
            "Đang chat với: tất cả mọi người" if recipient is None else f"Tin nhắn riêng tới: {sanitize(recipient)}"
        )

    def _update_counter(self) -> None:
        length = len(self._input.toPlainText().strip())
        self._counter.setText(f"{length}/{MAX_CHAT_LENGTH}")
        self._counter.setStyleSheet("color: #f38ba8;" if length > MAX_CHAT_LENGTH else "")

    def _on_send(self) -> None:
        if not self._connected:
            return
        text = self._input.toPlainText().strip()
        if not text:
            return
        if len(text) > MAX_CHAT_LENGTH:
            self.show_error(f"Tin nhắn quá dài (tối đa {MAX_CHAT_LENGTH} ký tự).")
            return
        self.clear_error()
        self._input.clear()
        self.send_requested.emit(text, self._users.get_selected_recipient())

    def _on_file(self) -> None:
        recipient = self._users.get_selected_recipient()
        if recipient is None:
            self.show_error("Hãy chọn một người dùng cụ thể ở danh sách bên trái để gửi tệp (không gửi broadcast).")
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Chọn tệp gửi cho {recipient}")
        if path:
            self.clear_error()
            self.file_send_requested.emit(path, recipient)

