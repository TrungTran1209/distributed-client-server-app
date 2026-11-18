"""Host screen: configure and run the collaboration server."""
from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..styles.theme import status_style
from ..widgets.cert_gen_dialog import CertGenDialog


def _spin(low: int, high: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    return box


class HostView(QWidget):
    start_requested = Signal(dict)
    stop_requested = Signal()
    connect_to_local_requested = Signal(str, int)
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._host_edit = QLineEdit("0.0.0.0")
        self._port_spin = _spin(1, 65535, 37021)
        self._udp_spin = _spin(1, 65535, 37020)
        self._advertise_edit = QLineEdit()
        self._advertise_edit.setPlaceholderText("Tự phát hiện nếu để trống (ví dụ 192.168.1.10)")
        self._cert_edit = QLineEdit("certs/server.crt" if Path("certs/server.crt").exists() else "")
        self._key_edit = QLineEdit("certs/server.key" if Path("certs/server.key").exists() else "")
        self._db_edit = QLineEdit("data/users.sqlite3")
        self._idle_spin = _spin(10, 3600, 90)
        self._auth_spin = _spin(5, 600, 60)

        form = QFormLayout()
        form.addRow("Địa chỉ lắng nghe", self._host_edit)
        form.addRow("Cổng TCP/TLS", self._port_spin)
        form.addRow("Cổng UDP discovery", self._udp_spin)
        form.addRow("Địa chỉ công bố", self._advertise_edit)
        form.addRow("Chứng chỉ (.crt)", self._file_row(self._cert_edit, "Chọn chứng chỉ", "Chứng chỉ (*.crt *.pem)"))
        form.addRow("Khóa riêng (.key)", self._file_row(self._key_edit, "Chọn khóa riêng", "Khóa (*.key *.pem)"))
        form.addRow("File CSDL tài khoản", self._db_edit)
        form.addRow("Idle timeout (giây)", self._idle_spin)
        form.addRow("Auth timeout (giây)", self._auth_spin)
        box = QGroupBox("Cấu hình máy chủ")
        box.setLayout(form)

        self._btn_certgen = QPushButton("Tạo chứng chỉ demo…")
        self._btn_certgen.clicked.connect(self._open_certgen)
        self._btn_start = QPushButton("Khởi chạy Server")
        self._btn_start.setObjectName("primary")
        self._btn_stop = QPushButton("Dừng Server")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setEnabled(False)
        self._btn_connect = QPushButton("Kết nối vào server này")
        self._btn_connect.setEnabled(False)
        self._btn_back = QPushButton("Quay lại")
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self.stop_requested)
        self._btn_connect.clicked.connect(self._on_connect_local)
        self._btn_back.clicked.connect(self.back_requested)

        buttons = QHBoxLayout()
        for widget in (self._btn_back, self._btn_certgen):
            buttons.addWidget(widget)
        buttons.addStretch()
        for widget in (self._btn_start, self._btn_stop, self._btn_connect):
            buttons.addWidget(widget)

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._status_label = QLabel("Server đang dừng")
        self._status_label.setStyleSheet(status_style("muted"))
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setPlaceholderText("Nhật ký hoạt động của server (không chứa mật khẩu/khóa)")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.addWidget(box)
        layout.addWidget(self._error_label)
        layout.addLayout(buttons)
        layout.addWidget(self._status_label)
        layout.addWidget(self._log_edit, 1)
        self._client_count = 0

    # ------------------------------------------------------------- helpers
    def _file_row(self, edit: QLineEdit, title: str, flt: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        browse = QPushButton("Chọn…")

        def _pick() -> None:
            path, _ = QFileDialog.getOpenFileName(self, title, "", f"{flt};;Tất cả (*)")
            if path:
                edit.setText(path)

        browse.clicked.connect(_pick)
        lay.addWidget(edit)
        lay.addWidget(browse)
        return row

    def _open_certgen(self) -> None:
        dialog = CertGenDialog(self)
        dialog.generated.connect(self._on_cert_generated)
        dialog.exec()

    def _on_cert_generated(self, cert: str, key: str) -> None:
        self._cert_edit.setText(cert)
        self._key_edit.setText(key)
        self.clear_error()

    # ----------------------------------------------------------------- API
    def get_config(self) -> dict:
        return {
            "host": self._host_edit.text().strip() or "0.0.0.0",
            "port": self._port_spin.value(),
            "udp_port": self._udp_spin.value(),
            "advertise_host": self._advertise_edit.text().strip() or None,
            "cert": self._cert_edit.text().strip(),
            "key": self._key_edit.text().strip(),
            "database": self._db_edit.text().strip() or "data/users.sqlite3",
            "idle_timeout": self._idle_spin.value(),
            "auth_timeout": self._auth_spin.value(),
        }

    def _on_start(self) -> None:
        config = self.get_config()
        if not config["cert"] or not config["key"]:
            self.set_error("Hãy chọn chứng chỉ và khóa riêng (hoặc bấm 'Tạo chứng chỉ demo').")
            return
        self.clear_error()
        self.start_requested.emit(config)

    def _on_connect_local(self) -> None:
        self.connect_to_local_requested.emit("127.0.0.1", self._port_spin.value())

    def set_error(self, text: str) -> None:
        self._error_label.setText(text)
        self._error_label.show()

    def clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()

    def set_running(self, running: bool) -> None:
        self._running = running
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._btn_connect.setEnabled(running)
        for widget in (self._host_edit, self._port_spin, self._udp_spin, self._cert_edit,
                       self._key_edit, self._db_edit, self._advertise_edit):
            widget.setEnabled(not running)
        self._render_status()

    def set_client_count(self, count: int) -> None:
        self._client_count = count
        self._render_status()

    def _render_status(self) -> None:
        if self._running:
            self._status_label.setText(
                f"Server đang chạy — {self._port_spin.value()} (TCP) · "
                f"{self._client_count} người trực tuyến"
            )
            self._status_label.setStyleSheet(status_style("success"))
        else:
            self._client_count = 0
            self._status_label.setText("Server đang dừng")
            self._status_label.setStyleSheet(status_style("muted"))

    def append_log(self, text: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_edit.append(f"[{stamp}] {text}")

    @property
    def running(self) -> bool:
        return self._running
