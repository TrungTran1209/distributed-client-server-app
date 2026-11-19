"""Join screen: Direct TLS address or UDP LAN discovery with vibrant Figma daylight card styling."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

_SERVER_ROLE = Qt.ItemDataRole.UserRole


def _clean(value: object) -> str:
    return "".join(ch for ch in str(value) if ch.isprintable())


class ConnectView(QWidget):
    connect_requested = Signal(str, int, str, str)  # host, port, ca path, download dir
    discover_requested = Signal(int)
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # Header Hero Card
        hero_card = QFrame()
        hero_card.setObjectName("card")
        hero_card.setStyleSheet(
            "QFrame#card { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #EEF2FF, stop:1 #FFFFFF); "
            "border: 1px solid #E0E7FF; border-radius: 14px; padding: 12px; }"
        )
        hero_lay = QVBoxLayout(hero_card)
        hero_badge = QLabel("✨ LUMICHAT SECURE CLIENT")
        hero_badge.setStyleSheet(
            "color: #4F46E5; font-weight: 800; font-size: 11px; letter-spacing: 0.8px; background: transparent;"
        )
        hero_title = QLabel("Tham gia Mạng làm việc Phân tán")
        hero_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #0F172A; background: transparent;")
        hero_desc = QLabel(
            "Kết nối an toàn tới máy chủ cộng tác qua kênh mã hóa TCP + TLS 1.2/1.3 và dò tìm máy chủ tự động qua UDP."
        )
        hero_desc.setStyleSheet("color: #64748B; font-size: 13px; background: transparent;")
        hero_desc.setWordWrap(True)
        hero_lay.addWidget(hero_badge)
        hero_lay.addWidget(hero_title)
        hero_lay.addWidget(hero_desc)

        # Direct Tab
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("IP hoặc tên miền máy chủ, ví dụ: 127.0.0.1 hoặc 192.168.1.10")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(37021)
        self._ca_edit = QLineEdit()
        self._ca_edit.setPlaceholderText("Tùy chọn: tệp chứng chỉ CA/Server để xác minh TLS (certs/server.crt)")
        self._download_edit = QLineEdit("downloads")

        self._btn_connect = QPushButton("Kết nối tới Máy chủ ➤")
        self._btn_connect.setObjectName("primary")
        self._btn_connect.clicked.connect(self._on_connect)

        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("Địa chỉ Máy chủ", self._host_edit)
        form.addRow("Cổng TCP/TLS", self._port_spin)
        form.addRow("Chứng chỉ CA (SAN)", self._pick_row(self._ca_edit, False))
        form.addRow("Thư mục Lưu tệp nhận", self._pick_row(self._download_edit, True))

        direct = QWidget()
        direct_lay = QVBoxLayout(direct)
        direct_lay.setContentsMargins(16, 16, 16, 16)
        direct_lay.setSpacing(14)
        direct_lay.addLayout(form)
        direct_lay.addWidget(self._btn_connect)
        direct_lay.addStretch()

        # LAN Discovery Tab
        self._udp_spin = QSpinBox()
        self._udp_spin.setRange(1, 65535)
        self._udp_spin.setValue(37020)
        self._broadcast_check = QCheckBox("Dùng LAN Broadcast (quét toàn bộ mạng cục bộ)")
        self._btn_discover = QPushButton("🔍 Khám phá Server qua UDP")
        self._btn_discover.clicked.connect(lambda: self.discover_requested.emit(self._udp_spin.value()))

        self._discovery_list = QListWidget()
        self._discovery_list.itemDoubleClicked.connect(lambda _item: self._connect_selected())
        self._btn_connect_selected = QPushButton("Kết nối tới Server đã chọn ➤")
        self._btn_connect_selected.setObjectName("primary")
        self._btn_connect_selected.clicked.connect(self._connect_selected)

        explain = QLabel(
            "🔒 Giao thức UDP Discovery chỉ hỗ trợ dò tìm địa chỉ máy chủ trong mạng. Sau khi tìm thấy, "
            "ứng dụng sẽ thiết lập kênh TLS bảo mật và kiểm tra chữ ký số chứng chỉ máy chủ."
        )
        explain.setObjectName("hint")
        explain.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(QLabel("Cổng UDP Discovery:"))
        row.addWidget(self._udp_spin)
        row.addWidget(self._btn_discover)
        row.addStretch()

        lan = QWidget()
        lan_lay = QVBoxLayout(lan)
        lan_lay.setContentsMargins(16, 16, 16, 16)
        lan_lay.setSpacing(12)
        lan_lay.addLayout(row)
        lan_lay.addWidget(self._broadcast_check)
        lan_lay.addWidget(self._discovery_list, 1)
        lan_lay.addWidget(explain)
        lan_lay.addWidget(self._btn_connect_selected)

        self._tabs = QTabWidget()
        self._tabs.addTab(direct, "🌐 Kết nối Trực tiếp (Direct TLS)")
        self._tabs.addTab(lan, "📡 Dò tìm Mạng LAN (UDP Discovery)")

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()

        self._btn_back = QPushButton("Quay lại")
        self._btn_back.clicked.connect(self.back_requested)

        card_wrapper = QFrame()
        card_wrapper.setObjectName("card")
        card_lay = QVBoxLayout(card_wrapper)
        card_lay.setContentsMargins(20, 20, 20, 20)
        card_lay.setSpacing(14)
        card_lay.addWidget(hero_card)
        card_lay.addWidget(self._tabs, 1)
        card_lay.addWidget(self._error_label)
        card_lay.addWidget(self._btn_back)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.addWidget(card_wrapper, 1)

    def _pick_row(self, edit: QLineEdit, directory: bool) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Chọn…")

        def _pick() -> None:
            if directory:
                path = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
            else:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Chọn chứng chỉ", "", "Chứng chỉ (*.crt *.pem *.cer);;Tất cả (*)"
                )
            if path:
                edit.setText(path)

        button.clicked.connect(_pick)
        lay.addWidget(edit)
        lay.addWidget(button)
        return row

    # ----------------------------------------------------------------- API
    def _emit_connect(self, host: str, port: int) -> None:
        if not host:
            self.set_error("Vui lòng nhập địa chỉ máy chủ.")
            return
        self.clear_error()
        self.connect_requested.emit(
            host, port, self._ca_edit.text().strip(), self._download_edit.text().strip() or "downloads"
        )

    def _on_connect(self) -> None:
        self._emit_connect(self._host_edit.text().strip(), self._port_spin.value())

    def _connect_selected(self) -> None:
        item = self._discovery_list.currentItem()
        if item is None:
            self.set_error("Hãy chọn một server trong danh sách.")
            return
        info = item.data(_SERVER_ROLE)
        self._emit_connect(info["host"], info["tcp_port"])

    def add_discovered_server(self, info: dict) -> None:
        host, port = _clean(info.get("host", "")), int(info.get("tcp_port", 37021))
        name = _clean(info.get("server_name", "collab"))
        item = QListWidgetItem(f"🛰️ {name} — {host}:{port}")
        item.setData(_SERVER_ROLE, {"host": host, "tcp_port": port})
        self._discovery_list.addItem(item)
        self._discovery_list.setCurrentItem(item)

    def clear_discovered(self) -> None:
        self._discovery_list.clear()

    def set_discovering(self, active: bool) -> None:
        self._btn_discover.setEnabled(not active)
        self._btn_discover.setText("Đang dò tìm…" if active else "Khám phá Server qua UDP")

    def broadcast_enabled(self) -> bool:
        return self._broadcast_check.isChecked()

    def set_connecting(self, active: bool) -> None:
        self._btn_connect.setEnabled(not active)
        self._btn_connect_selected.setEnabled(not active)
        self._btn_connect.setText("Đang kết nối…" if active else "Kết nối tới Máy chủ ➤")

    def prefill(self, host: str, port: int, ca: str = "") -> None:
        self._host_edit.setText(host)
        self._port_spin.setValue(port)
        if ca:
            self._ca_edit.setText(ca)
        self._tabs.setCurrentIndex(0)

    def set_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.show()

    def clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()
