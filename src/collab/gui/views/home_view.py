"""Home screen: choose between hosting a server or joining one."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ..styles.theme import status_style


class HomeView(QWidget):
    host_requested = Signal()
    join_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("Collab")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = QLabel("Trò chuyện và gửi tệp an toàn trong mạng nội bộ của bạn")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._btn_host = QPushButton("Tạo máy chủ (Host)\nChạy server trên máy này để người khác kết nối")
        self._btn_join = QPushButton("Tham gia máy chủ (Join)\nKết nối tới server có sẵn trong mạng")
        for btn in (self._btn_host, self._btn_join):
            btn.setObjectName("hero")
            btn.setMinimumWidth(300)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_host.clicked.connect(self.host_requested)
        self._btn_join.clicked.connect(self.join_requested)

        self._status_label = QLabel("Chưa kết nối")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_status("Chưa kết nối", "muted")

        buttons = QHBoxLayout()
        buttons.setSpacing(24)
        buttons.addStretch()
        buttons.addWidget(self._btn_host)
        buttons.addWidget(self._btn_join)
        buttons.addStretch()

        note = QLabel(
            "Lưu ý: lịch sử chat chỉ tồn tại trong phiên hiện tại (không được lưu). "
            "Kết nối được bảo vệ bằng TLS; chứng chỉ luôn được xác minh."
        )
        note.setObjectName("hint")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 32)
        layout.addStretch(2)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(36)
        layout.addLayout(buttons)
        layout.addSpacing(24)
        layout.addWidget(self._status_label)
        layout.addStretch(3)
        layout.addWidget(note)

    def set_status(self, text: str, status_type: str = "info") -> None:
        self._status_label.setText(text)
        self._status_label.setStyleSheet(status_style(status_type))
        self._status_label.show()
