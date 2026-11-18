"""A single chat message bubble styled for the Vibrant Light Theme (plain text only)."""

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
        card.setMaximumWidth(580)

        if is_own:
            card.setStyleSheet(
                "QFrame#card { background: #4F46E5; border-radius: 14px; border: none; }"
            )
            head_color = "#E0E7FF"
            body_color = "#FFFFFF"
            meta_color = "#C7D2FE"
            badge_style = (
                "color: #FFFFFF; background: #F97316; border-radius: 6px; "
                "padding: 1px 6px; font-size: 11px; font-weight: 700;"
            )
        else:
            card.setStyleSheet(
                "QFrame#card { background: #FFFFFF; border-radius: 14px; border: 1px solid #E2E8F0; }"
            )
            head_color = "#0284C7"
            body_color = "#0F172A"
            meta_color = "#64748B"
            badge_style = (
                "color: #C2410C; background: #FFEDD5; border-radius: 6px; "
                "padding: 1px 6px; font-size: 11px; font-weight: 700;"
            )

        head = QLabel(sanitize(sender) if not is_own else "Bạn")
        head.setStyleSheet(f"font-weight: 700; color: {head_color}; background: transparent;")
        head.setTextFormat(Qt.TextFormat.PlainText)

        self._body = QLabel(sanitize(text))
        self._body.setTextFormat(Qt.TextFormat.PlainText)
        self._body.setWordWrap(True)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setStyleSheet(f"color: {body_color}; background: transparent; font-size: 13px;")

        meta = QLabel(sanitize(timestamp))
        meta.setStyleSheet(f"color: {meta_color}; font-size: 11px; background: transparent;")

        badge_text = "Riêng tư" + (f" → {sanitize(private_peer)}" if private_peer else "")
        self._badge = QLabel(badge_text)
        self._badge.setStyleSheet(badge_style)
        self._badge.setVisible(bool(is_private))

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(head)
        top.addWidget(self._badge)
        top.addStretch()
        top.addWidget(meta)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(14, 10, 14, 10)
        inner.setSpacing(4)
        inner.addLayout(top)
        inner.addWidget(self._body)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 3, 4, 3)
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
