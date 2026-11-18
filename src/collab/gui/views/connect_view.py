"""Join screen: direct address or UDP LAN discovery."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFormLayout,
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
        self._host_edit = QLineEdit()
        self._host_edit.setPlaceholderText("IP hoặc tên máy chủ, ví dụ 192.168.1.10")
        self._port_spin = QSpinBox()
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(37021)
        self._ca_edit = QLineEdit()
        self._ca_edit.setPlaceholderText("Tùy chọn: file chứng chỉ/CA của server (server.crt)")
        self._download_edit = QLineEdit("downloads")
        self._btn_connect = QPushButton("Kết nối")
        self._btn_connect.setObjectName("primary")
        self._btn_connect.clicked.connect(self._on_connect)

        form = QFormLayout()
        form.addRow("Máy chủ", self._host_edit)
        form.addRow("Cổng TCP", self._port_spin)
        form.addRow("Chứng chỉ CA", self._pick_row(self._ca_edit, False))
        form.addRow("Thư mục lưu tệp nhận", self._pick_row(self._download_edit, True))
        direct = QWidget()
        direct_lay = QVBoxLayout(direct)
        direct_lay.addLayout(form)
        direct_lay.addWidget(self._btn_connect)
        direct_lay.addStretch()

        self._udp_spin = QSpinBox()
        self._udp_spin.setRange(1, 65535)
        self._udp_spin.setValue(37020)
        self._broadcast_check = QCheckBox("Dùng LAN broadcast (mặc định: tìm trên máy này)")
        self._btn_discover = QPushButton("Khám phá Server")
        self._btn_discover.clicked.connect(lambda: self.discover_requested.emit(self._udp_spin.value()))
        self._discovery_list = QListWidget()
        self._discovery_list.itemDoubleClicked.connect(lambda _item: self._connect_selected())
        self._btn_connect_selected = QPushButton("Kết nối tới server đã chọn")
        self._btn_connect_selected.setObjectName("primary")
        self._btn_connect_selected.clicked.connect(self._connect_selected)
        explain = QLabel(
            "UDP chỉ giúp tìm địa chỉ server. Sau đó ứng dụng vẫn kết nối TLS và xác minh "
            "chứng chỉ — không tin tưởng địa chỉ chỉ vì nó trả lời."
        )
        explain.setObjectName("hint")
        explain.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(QLabel("Cổng UDP"))
        row.addWidget(self._udp_spin)
        row.addWidget(self._btn_discover)
        row.addStretch()
        lan = QWidget()
        lan_lay = QVBoxLayout(lan)
        lan_lay.addLayout(row)
        lan_lay.addWidget(self._broadcast_check)
        lan_lay.addWidget(self._discovery_list, 1)
        lan_lay.addWidget(explain)
        lan_lay.addWidget(self._btn_connect_selected)

        self._tabs = QTabWidget()
        self._tabs.addTab(direct, "Kết nối trực tiếp")
        self._tabs.addTab(lan, "Dò tìm mạng LAN")

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._btn_back = QPushButton("Quay lại")
        self._btn_back.clicked.connect(self.back_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addWidget(self._tabs, 1)
        layout.addWidget(self._error_label)
        layout.addWidget(self._btn_back)

    def _pick_row(self, edit: QLineEdit, directory: bool) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        button = QPushButton("Chọn…")

        def _pick() -> None:
            if directory:
                path = QFileDialog.getExistingDirectory(self, "Chọn thư mục")
            else:
                path, _ = QFileDialog.getOpenFileName(self, "Chọn chứng chỉ", "", "Chứng chỉ (*.crt *.pem *.cer);;Tất cả (*)")
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
        item = QListWidgetItem(f"{name} — {host}:{port}")
        item.setData(_SERVER_ROLE, {"host": host, "tcp_port": port})
        self._discovery_list.addItem(item)
        self._discovery_list.setCurrentItem(item)

    def clear_discovered(self) -> None:
        self._discovery_list.clear()

    def set_discovering(self, active: bool) -> None:
        self._btn_discover.setEnabled(not active)
        self._btn_discover.setText("Đang dò tìm…" if active else "Khám phá Server")

    def broadcast_enabled(self) -> bool:
        return self._broadcast_check.isChecked()

    def set_connecting(self, active: bool) -> None:
        self._btn_connect.setEnabled(not active)
        self._btn_connect_selected.setEnabled(not active)
        self._btn_connect.setText("Đang kết nối…" if active else "Kết nối")

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
