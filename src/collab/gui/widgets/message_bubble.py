"""A single chat message bubble styled with vibrant Figma daylight messaging aesthetics."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .formatting import sanitize

_AVATAR_COLORS = [
    ("#4F46E5", "#EEF2FF"),  # Indigo
    ("#0284C7", "#E0F2FE"),  # Sky
    ("#059669", "#DCFCE7"),  # Emerald
    ("#D97706", "#FEF3C7"),  # Amber
    ("#7C3AED", "#F3E8FF"),  # Purple
    ("#E11D48", "#FFE4E6"),  # Rose
]


def _avatar_colors(name: str) -> tuple[str, str]:
    idx = sum(ord(c) for c in name) % len(_AVATAR_COLORS)
    return _AVATAR_COLORS[idx]


def _avatar_circle(letter: str, fg: str, bg: str) -> QLabel:
    lbl = QLabel(letter[:1].upper())
    lbl.setFixedSize(30, 30)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lbl.setStyleSheet(
        f"QLabel {{ background: {bg}; color: {fg}; border-radius: 15px; font-weight: 800; font-size: 13px; }}"
    )
    return lbl


class MessageBubble(QWidget):
    def __init__(
        self,
        text: str,
        sender: str,
        timestamp: str,
        is_own: bool,
        is_private: bool,
        private_peer: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setProperty("own", bool(is_own))
        clean_sender = sanitize(sender) or "User"

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(600)

        fg_av, bg_av = _avatar_colors(clean_sender)
        avatar = _avatar_circle("Bạn" if is_own else clean_sender, "#4F46E5" if is_own else fg_av, "#EEF2FF" if is_own else bg_av)

        if is_own:
            card.setStyleSheet(
                "QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #4F46E5, stop:1 #4338CA); "
                "border-radius: 14px; border: none; padding: 2px; }"
            )
            head_color = "#E0E7FF"
            body_color = "#FFFFFF"
            meta_color = "#C7D2FE"
            badge_style = (
                "color: #FFFFFF; background: #F97316; border-radius: 6px; "
                "padding: 2px 7px; font-size: 11px; font-weight: 700;"
            )
        else:
            card.setStyleSheet(
                "QFrame#card { background: #FFFFFF; border-radius: 14px; border: 1px solid #E2E8F0; padding: 2px; }"
            )
            head_color = fg_av
            body_color = "#0F172A"
            meta_color = "#64748B"
            badge_style = (
                "color: #C2410C; background: #FFEDD5; border-radius: 6px; "
                "padding: 2px 7px; font-size: 11px; font-weight: 700;"
            )

        head = QLabel("Bạn" if is_own else clean_sender)
        head.setStyleSheet(f"font-weight: 700; color: {head_color}; background: transparent; font-size: 12px;")
        head.setTextFormat(Qt.TextFormat.PlainText)

        self._body = QLabel(sanitize(text))
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setStyleSheet(f"color: {body_color}; background: transparent; font-size: 13px; line-height: 1.4;")

        meta = QLabel(sanitize(timestamp))
        meta.setStyleSheet(f"color: {meta_color}; font-size: 11px; background: transparent; font-weight: 500;")

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(head)
        top.addStretch()
        top.addWidget(meta)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(5)
        inner.addLayout(top)
        inner.addWidget(self._body)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)

        if is_own:
            row.addStretch()
            row.addWidget(card)
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignBottom)
        else:
            row.addWidget(avatar, 0, Qt.AlignmentFlag.AlignBottom)
            row.addWidget(card)
            row.addStretch()

    def body_text(self) -> str:
        return self._body.text()

    def text_format(self) -> Qt.TextFormat:
        return self._body.textFormat()

    def is_private_badge_shown(self) -> bool:
        return False


class FileMessageBubble(QWidget):
    download_requested = Signal(str)

    def __init__(
        self,
        transfer_id: str,
        filename: str,
        size: int,
        sender: str,
        timestamp: str,
        is_own: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.transfer_id = transfer_id
        clean_sender = sanitize(sender) or "User"

        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(520)
        card.setStyleSheet(
            "QFrame#card { background: #FFFFFF; border: 1px solid #E2E8F0; "
            "border-radius: 10px; }"
        )

        ext = filename.rsplit(".", 1)[-1].upper()[:4] if "." in filename else "FILE"
        icon = QLabel(ext)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "QLabel { background: #FF6B6B; color: #FFFFFF; border-radius: 7px; "
            "font-size: 12px; font-weight: 800; }"
        )

        name = QLabel(sanitize(filename))
        name.setStyleSheet("font-size: 14px; font-weight: 700; color: #0F172A;")
        name.setTextFormat(Qt.TextFormat.PlainText)

        self._status = QLabel(
            f"{_format_file_size(size)}  ·  Đã gửi"
            if is_own
            else f"{_format_file_size(size)}  ·  Tải về để xem"
        )
        self._status.setStyleSheet("font-size: 11px; color: #64748B;")

        meta = QLabel(f"{sanitize(timestamp)}")
        meta.setStyleSheet("font-size: 10px; color: #94A3B8;")

        download = QPushButton("↓")
        download.setFixedSize(38, 38)
        download.setToolTip("Tải xuống")
        download.setStyleSheet(
            "QPushButton { background: #FFFFFF; color: #334155; border: 1px solid #CBD5E1; "
            "border-radius: 7px; font-size: 18px; }"
            "QPushButton:hover { background: #EEF2FF; border-color: #4F46E5; color: #4F46E5; }"
        )
        download.clicked.connect(lambda: self.download_requested.emit(self.transfer_id))
        download.clicked.connect(download.hide)
        download.clicked.connect(lambda: self._status.setText(f"{_format_file_size(size)}  ·  Đang tải xuống"))
        if is_own:
            download.hide()

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(name)
        text_col.addWidget(self._status)
        text_col.addWidget(meta)

        inner = QHBoxLayout(card)
        inner.setContentsMargins(10, 8, 10, 8)
        inner.setSpacing(10)
        inner.addWidget(icon)
        inner.addLayout(text_col, 1)
        inner.addWidget(download)

        row = QHBoxLayout(self)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(8)
        if is_own:
            row.addStretch()
            row.addWidget(card)
        else:
            row.addWidget(card)
            row.addStretch()

    def download_button(self) -> QPushButton:
        return self.findChildren(QPushButton)[0]

    def mark_done(self) -> None:
        download = self.findChildren(QPushButton)
        if download:
            download[0].hide()
        self._status.setText("Đã hoàn tất")


def _format_file_size(size: int) -> str:
    value = max(0, int(size))
    units = ("B", "KB", "MB", "GB")
    unit_index = 0
    float_value = float(value)
    while float_value >= 1024 and unit_index < len(units) - 1:
        float_value /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{value} B"
    return f"{float_value:.2f}".rstrip("0").rstrip(".") + f" {units[unit_index]}"
