"""LumiChat Client workspace view: Online/Offline user tables, persistent per-peer chat, and 1-click file send."""

from __future__ import annotations

from collections import defaultdict
import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
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

MAX_CHAT_LENGTH = 4000


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
        self._conversations: dict[str | None, list[dict]] = defaultdict(list)
        self._seen_ids: set[str] = set()

        # Top bar
        top_card = QFrame()
        top_card.setObjectName("card")
        self._brand_label = QLabel("✨ LumiChat")
        self._brand_label.setStyleSheet("font-size: 17px; font-weight: 800; color: #4F46E5;")
        self._server_label = QLabel("")
        self._server_label.setStyleSheet("color: #64748B; font-weight: 600;")
        self._user_label = QLabel("")
        self._user_label.setStyleSheet(
            "font-weight: 700; color: #0284C7; background: #E0F2FE; "
            "border-radius: 8px; padding: 4px 10px;"
        )
        self._btn_transfers = QPushButton("📦 Tiến độ Tệp")
        self._btn_transfers.clicked.connect(self.transfers_panel_requested)
        self._btn_logout = QPushButton("Đăng xuất")
        self._btn_logout.clicked.connect(self.logout_requested)
        header = QHBoxLayout(top_card)
        header.setContentsMargins(14, 10, 14, 10)
        header.addWidget(self._brand_label)
        header.addSpacing(10)
        header.addWidget(self._server_label)
        header.addStretch()
        header.addWidget(self._user_label)
        header.addWidget(self._btn_transfers)
        header.addWidget(self._btn_logout)

        # Disconnected banner
        self._banner = QWidget()
        self._banner.setObjectName("banner")
        self._banner_text = QLabel("")
        self._banner_text.setObjectName("banner")
        self._btn_reconnect = QPushButton("Kết nối lại")
        self._btn_reconnect.setObjectName("primary")
        self._btn_reconnect.clicked.connect(self.reconnect_requested)
        banner_lay = QHBoxLayout(self._banner)
        banner_lay.setContentsMargins(8, 4, 8, 4)
        banner_lay.addWidget(self._banner_text, 1)
        banner_lay.addWidget(self._btn_reconnect)
        self._banner.hide()

        # Left sidebar: Online & Offline User Tables
        self._users = UserListWidget()
        self._users.setMinimumWidth(260)
        users_title = QLabel("DANH BẠ NGƯỜI DÙNG")
        users_title.setStyleSheet("font-weight: 800; color: #4F46E5; font-size: 12px;")
        self._online_label = QLabel("0 trực tuyến · 0 ngoại tuyến")
        self._online_label.setObjectName("hint")
        side = QWidget()
        side.setObjectName("sidebar")
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(12, 12, 12, 12)
        side_lay.addWidget(users_title)
        side_lay.addWidget(self._users, 1)
        side_lay.addWidget(self._online_label)

        # Right conversation area
        conv_header = QFrame()
        conv_header.setObjectName("card")
        self._conv_title = QLabel("📢 Kênh chung (Broadcast)")
        self._conv_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #0F172A;")
        self._conv_badge = QLabel("Mọi thành viên")
        self._conv_badge.setStyleSheet(
            "color: #059669; background: #DCFCE7; border-radius: 8px; padding: 3px 10px; font-weight: 700;"
        )
        conv_head_lay = QHBoxLayout(conv_header)
        conv_head_lay.setContentsMargins(14, 8, 14, 8)
        conv_head_lay.addWidget(self._conv_title)
        conv_head_lay.addStretch()
        conv_head_lay.addWidget(self._conv_badge)

        self._notice = QLabel(
            "Lịch sử tin nhắn được lưu giữ tự động trên máy chủ — nhắn tin cho cả người đang trực tuyến và ngoại tuyến."
        )
        self._notice.setObjectName("hint")
        self._notice.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._messages = QVBoxLayout()
        self._messages.setAlignment(Qt.AlignmentFlag.AlignTop)
        holder = QWidget()
        holder.setStyleSheet("background: #F8FAFC;")
        holder.setLayout(self._messages)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(holder)

        self._input = _Composer()
        self._input.setPlaceholderText("Nhập tin nhắn… (Enter để gửi, Shift+Enter xuống dòng)")
        self._input.setMaximumHeight(82)
        self._input.submit.connect(self._on_send)
        self._input.textChanged.connect(self._update_counter)
        self._counter = QLabel(f"0/{MAX_CHAT_LENGTH}")
        self._counter.setObjectName("hint")
        self._btn_send = QPushButton("Gửi tin ➤")
        self._btn_send.setObjectName("primary")
        self._btn_send.clicked.connect(self._on_send)
        self._btn_file = QPushButton("📎 Gửi tệp nhanh")
        self._btn_file.setObjectName("accent_coral")
        self._btn_file.clicked.connect(self._on_file)

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._info_banner = QLabel("")
        self._info_banner.setStyleSheet(
            "color: #B45309; background: #FEF3C7; border: 1px solid #FDE68A; "
            "border-radius: 8px; padding: 6px 10px; font-weight: 600;"
        )
        self._info_banner.hide()

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
        right_lay.setContentsMargins(12, 6, 6, 6)
        right_lay.addWidget(conv_header)
        right_lay.addWidget(self._notice)
        right_lay.addWidget(self._scroll, 1)
        right_lay.addWidget(self._info_banner)
        right_lay.addWidget(self._error_label)
        right_lay.addLayout(meta)
        right_lay.addLayout(composer)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(side)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([280, 740])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(top_card)
        layout.addWidget(self._banner)
        layout.addWidget(splitter, 1)
        self._on_recipient_changed(None)

    # ------------------------------------------------------------- state
    def set_connection_info(self, host: str, port: int, username: str) -> None:
        self._username = username
        self._users.set_own_username(username)
        self._server_label.setText(f"Kết nối: {sanitize(host)}:{port}")
        self._user_label.setText(f"👤 {sanitize(username)}")

    def set_users(self, users: list[dict]) -> None:
        self._users.set_users(users)
        self._refresh_counts_and_header()

    def set_directory(self, directory: list[dict]) -> None:
        self._users.set_directory(directory)
        self._refresh_counts_and_header()

    def _refresh_counts_and_header(self) -> None:
        n_on = len(self._users.online_usernames())
        n_off = len(self._users.offline_usernames())
        self._online_label.setText(f"{n_on} trực tuyến · {n_off} ngoại tuyến (ngoài bạn)")
        self._update_conversation_header(self._users.get_selected_recipient())

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
        self._info_banner.hide()
        self._error_label.setText(text)
        self._error_label.show()

    def show_offline_queued_notice(self, recipient: str) -> None:
        self.clear_error()
        self._info_banner.setText(
            f"Đã lưu tin nhắn cho {sanitize(recipient)} — họ sẽ thấy ngay khi trực tuyến trở lại."
        )
        self._info_banner.show()
        QTimer.singleShot(5000, self._info_banner.hide)

    def clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()

    def clear_messages(self) -> None:
        self._conversations.clear()
        self._seen_ids.clear()
        self._clear_rendered_bubbles()

    def _clear_rendered_bubbles(self) -> None:
        while self._messages.count():
            item = self._messages.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._count = 0

    def message_count(self) -> int:
        return self._count

    # ---------------------------------------------------------- messages
    def _conversation_key(self, message: dict) -> str | None:
        recipient = message.get("to")
        if recipient is None:
            return None
        sender = sanitize(message.get("from") or self._username)
        target = sanitize(recipient)
        return target if sender == self._username else sender

    @staticmethod
    def _format_stamp(raw_sent_at: object) -> str:
        if isinstance(raw_sent_at, str) and raw_sent_at:
            if "T" in raw_sent_at and len(raw_sent_at) >= 16:
                return raw_sent_at[11:16]
            return raw_sent_at[:16]
        return datetime.datetime.now().strftime("%H:%M")

    def load_history(self, messages: list[dict]) -> None:
        """Populate broadcast and 1-to-1 conversation timelines from server SQLite history."""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            mid = str(msg.get("message_id") or "")
            if mid and mid in self._seen_ids:
                continue
            if mid:
                self._seen_ids.add(mid)
            key = self._conversation_key(msg)
            self._conversations[key].append(dict(msg))
        self._render_conversation(self._users.get_selected_recipient())

    def add_message(self, message: dict) -> None:
        mid = str(message.get("message_id") or "")
        if mid and mid in self._seen_ids:
            return
        if mid:
            self._seen_ids.add(mid)
        key = self._conversation_key(message)
        self._conversations[key].append(dict(message))
        current = self._users.get_selected_recipient()
        if key == current:
            self._append_bubble(message)
        else:
            self._users.increment_unread(key)

    def _render_conversation(self, key: str | None) -> None:
        self._clear_rendered_bubbles()
        for msg in self._conversations.get(key, []):
            self._append_bubble(msg)

    def _append_bubble(self, message: dict) -> None:
        sender = sanitize(message.get("from") or self._username)
        recipient = message.get("to")
        is_own = bool(self._username and sender == self._username)
        stamp = self._format_stamp(message.get("sent_at"))
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
        QTimer.singleShot(
            0,
            lambda: self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()
            ),
        )

    # ----------------------------------------------------------- handlers
    def _update_conversation_header(self, recipient: str | None) -> None:
        if recipient is None:
            self._conv_title.setText("📢 Kênh chung (Tất cả mọi người)")
            self._conv_badge.setText("Kênh chung · Lưu lịch sử")
            self._conv_badge.setStyleSheet(
                "color: #4338CA; background: #EEF2FF; border-radius: 8px; padding: 3px 10px; font-weight: 700;"
            )
            self._target_label.setText("Đang nhắn tới: tất cả mọi người (Broadcast)")
        else:
            online = self._users.is_user_online(recipient)
            self._conv_title.setText(f"💬 Hội thoại với {sanitize(recipient)}")
            if online:
                self._conv_badge.setText("● Đang trực tuyến")
                self._conv_badge.setStyleSheet(
                    "color: #047857; background: #DCFCE7; border-radius: 8px; padding: 3px 10px; font-weight: 700;"
                )
                self._target_label.setText(f"Tin nhắn riêng & gửi tệp tới: {sanitize(recipient)}")
            else:
                self._conv_badge.setText("○ Ngoại tuyến · Vẫn nhận & lưu tin nhắn")
                self._conv_badge.setStyleSheet(
                    "color: #475569; background: #F1F5F9; border-radius: 8px; padding: 3px 10px; font-weight: 700;"
                )
                self._target_label.setText(
                    f"Nhắn ngoại tuyến tới: {sanitize(recipient)} (sẽ hiển thị khi họ online)"
                )

    def _on_recipient_changed(self, recipient: str | None) -> None:
        self.clear_error()
        self._info_banner.hide()
        self._users.clear_unread(recipient)
        self._update_conversation_header(recipient)
        self._render_conversation(recipient)

    def _update_counter(self) -> None:
        length = len(self._input.toPlainText().strip())
        self._counter.setText(f"{length}/{MAX_CHAT_LENGTH}")
        self._counter.setStyleSheet("color: #EF4444; font-weight: 700;" if length > MAX_CHAT_LENGTH else "")

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
            self.show_error(
                "Hãy chọn một người dùng cụ thể ở bảng Trực tuyến bên trái để gửi tệp (không gửi broadcast)."
            )
            return
        if not self._users.is_user_online(recipient):
            self.show_error(
                f"{sanitize(recipient)} hiện đang ngoại tuyến — bạn vẫn nhắn tin được, nhưng gửi tệp chia chunk cần người nhận đang trực tuyến."
            )
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Chọn tệp gửi ngay cho {recipient}")
        if path:
            self.clear_error()
            self.file_send_requested.emit(path, recipient)
