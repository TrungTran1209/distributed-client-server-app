"""A single chat message bubble styled with vibrant Figma daylight messaging aesthetics."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

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

        badge_text = "🔒 Riêng tư" + (f" → {sanitize(private_peer)}" if private_peer else "")
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
        return not self._badge.isHidden()
