"""A single chat message bubble (plain text only — never interpreted as HTML)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .formatting import sanitize


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
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(560)
        bg = "#3b5b9a" if is_own else "#2a2b3d"
        card.setStyleSheet(f"QFrame#card {{ background: {bg}; border-radius: 10px; border: none; }}")

        head = QLabel(sanitize(sender) if not is_own else "Bạn")
        head.setStyleSheet("font-weight: 600; color: #89b4fa; background: transparent;")
        head.setTextFormat(Qt.TextFormat.PlainText)
        self._body = QLabel(sanitize(text))
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setStyleSheet("background: transparent;")
        meta = QLabel(timestamp)
        meta.setStyleSheet("color: #8a8fb0; font-size: 11px; background: transparent;")
        self._badge = QLabel("riêng tư" + (f" → {sanitize(private_peer)}" if private_peer else ""))
        self._badge.setStyleSheet("color: #fab387; font-size: 11px; font-weight: 600; background: transparent;")
        self._badge.setVisible(bool(is_private))

        top = QHBoxLayout()
        top.addWidget(head)
        top.addWidget(self._badge)
        top.addStretch()
        top.addWidget(meta)
        inner = QVBoxLayout(card)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.addLayout(top)
        inner.addWidget(self._body)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 2, 0, 2)
        if is_own:
            row.addStretch()
        row.addWidget(card)
        if not is_own:
            row.addStretch()

    def body_text(self) -> str:
        return self._body.text()

    def text_format(self) -> Qt.TextFormat:
        return self._body.textFormat()

    def is_private_badge_shown(self) -> bool:
        return not self._badge.isHidden()
