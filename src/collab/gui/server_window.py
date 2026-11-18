"""Standalone LumiChat Server Console — Server Configuration, Online/Offline User Table,
and Real-Time Packet/Chunk & Operation Trace Inspector.
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .controllers.server_controller import ServerController
from .styles.theme import APP_BRAND
from .widgets.cert_gen_dialog import CertGenDialog
from .widgets.formatting import human_size, sanitize

_MAX_TRACE_ROWS = 2000

_CATEGORY_COLORS = {
    "CHUNK": ("#EA580C", "#FFEDD5"),
    "FILE": ("#0284C7", "#E0F2FE"),
    "CHAT": ("#4F46E5", "#EEF2FF"),
    "AUTH": ("#059669", "#DCFCE7"),
    "SESSION": ("#7C3AED", "#F3E8FF"),
    "ERROR": ("#DC2626", "#FEE2E2"),
}


def _spin(low: int, high: int, value: int) -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setValue(value)
    return box


def _kpi_card(title: str, initial: str, accent_hex: str) -> tuple[QFrame, QLabel]:
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(
        f"QFrame#card {{ background: #FFFFFF; border: 1px solid #E2E8F0; "
        f"border-left: 5px solid {accent_hex}; border-radius: 10px; }}"
    )
    lbl_title = QLabel(title)
    lbl_title.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 700;")
    lbl_val = QLabel(initial)
    lbl_val.setStyleSheet(f"color: {accent_hex}; font-size: 18px; font-weight: 800;")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(2)
    lay.addWidget(lbl_title)
    lay.addWidget(lbl_val)
    return card, lbl_val


class ServerMainWindow(QMainWindow):
    """Dedicated Server management & real-time chunk/operation trace dashboard."""

    def __init__(self, server_ctrl: ServerController) -> None:
        super().__init__()
        self.server_ctrl = server_ctrl
        self.setWindowTitle(f"{APP_BRAND} Server Console — Quản trị & Trace Gói Chunk")
        self.setMinimumSize(1120, 720)

        self._directory: list[dict] = []
        self._chunk_count = 0
        self._msg_count = 0
        self._active_filter = "ALL"

        # Top Banner + KPI row
        top_row = QHBoxLayout()
        brand_box = QVBoxLayout()
        title = QLabel(f"🛰️ {APP_BRAND} Server Console")
        title.setObjectName("title")
        subtitle = QLabel("Khởi tạo máy chủ TLS & Theo dõi trực tiếp lịch sử gói Chunk và thao tác hệ thống")
        subtitle.setObjectName("subtitle")
        brand_box.addWidget(title)
        brand_box.addWidget(subtitle)
        top_row.addLayout(brand_box, 2)

        kpi_status_card, self._kpi_status = _kpi_card("TRẠNG THÁI SERVER", "Đang dừng", "#64748B")
        kpi_users_card, self._kpi_users = _kpi_card("NGƯỜI DÙNG (ON / OFF)", "0 Online · 0 Offline", "#10B981")
        kpi_chunks_card, self._kpi_chunks = _kpi_card("GÓI CHUNK ĐÃ RELAY", "0 chunks", "#F97316")
        kpi_msgs_card, self._kpi_msgs = _kpi_card("TIN NHẮN LƯU TRỮ", "0 tin", "#4F46E5")
        for card in (kpi_status_card, kpi_users_card, kpi_chunks_card, kpi_msgs_card):
            top_row.addWidget(card, 1)

        # Left column: Server creation form + system log
        self._host_edit = QLineEdit("0.0.0.0")
        self._port_spin = _spin(1, 65535, 37021)
        self._udp_spin = _spin(1, 65535, 37020)
        self._advertise_edit = QLineEdit()
        self._advertise_edit.setPlaceholderText("Tự phát hiện IP LAN nếu để trống")
        self._cert_edit = QLineEdit("certs/server.crt" if Path("certs/server.crt").exists() else "")
        self._key_edit = QLineEdit("certs/server.key" if Path("certs/server.key").exists() else "")
        self._db_edit = QLineEdit("data/users.sqlite3")
        self._idle_spin = _spin(10, 3600, 90)
        self._auth_spin = _spin(5, 600, 60)

        form = QFormLayout()
        form.addRow("Bind IP", self._host_edit)
        form.addRow("Cổng TCP/TLS", self._port_spin)
        form.addRow("Cổng UDP", self._udp_spin)
        form.addRow("IP công bố", self._advertise_edit)
        form.addRow("Chứng chỉ (.crt)", self._file_row(self._cert_edit, "Chọn chứng chỉ", "Chứng chỉ (*.crt *.pem)"))
        form.addRow("Khóa riêng (.key)", self._file_row(self._key_edit, "Chọn khóa riêng", "Khóa (*.key *.pem)"))
        form.addRow("SQLite DB", self._db_edit)
        form.addRow("Idle timeout (s)", self._idle_spin)
        form.addRow("Auth timeout (s)", self._auth_spin)

        cfg_box = QGroupBox("Khởi tạo Máy chủ")
        cfg_lay = QVBoxLayout(cfg_box)
        cfg_lay.addLayout(form)

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        cfg_lay.addWidget(self._error_label)

        self._btn_certgen = QPushButton("🔐 Tạo chứng chỉ TLS (SAN)…")
        self._btn_certgen.clicked.connect(self._open_certgen)
        self._btn_start = QPushButton("▶ Khởi chạy Server")
        self._btn_start.setObjectName("primary")
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop = QPushButton("⏹ Dừng Server")
        self._btn_stop.setObjectName("danger")
        self._btn_stop.setEnabled(False)
        self._btn_stop.clicked.connect(self._on_stop)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_stop)
        cfg_lay.addWidget(self._btn_certgen)
        cfg_lay.addLayout(btn_row)

        # Registered Users Table (Online + Offline)
        users_box = QGroupBox("Danh bạ Tài khoản (Trực tuyến & Ngoại tuyến)")
        self._users_table = QTableWidget(0, 3)
        self._users_table.setHorizontalHeaderLabels(["Tài khoản", "Trạng thái", "Địa chỉ kết nối"])
        self._users_table.verticalHeader().setVisible(False)
        self._users_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._users_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        uh = self._users_table.horizontalHeader()
        uh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        uh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        uh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        users_lay = QVBoxLayout(users_box)
        users_lay.addWidget(self._users_table)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setMaximumHeight(110)
        self._log_edit.setPlaceholderText("Nhật ký hệ thống máy chủ…")

        left_col = QWidget()
        left_lay = QVBoxLayout(left_col)
        left_lay.setContentsMargins(0, 0, 8, 0)
        left_lay.addWidget(cfg_box)
        left_lay.addWidget(users_box, 1)
        left_lay.addWidget(self._log_edit)

        # Right column: Live Chunk & Operation Trace Table
        trace_box = QGroupBox("Lịch sử Trace Gói Chunk & Thao tác Thời gian thực")
        filter_bar = QHBoxLayout()
        filter_bar.addWidget(QLabel("Bộ lọc:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItem("Tất cả thao tác", "ALL")
        self._filter_combo.addItem("Chỉ gói Chunk (CHUNK)", "CHUNK")
        self._filter_combo.addItem("Truyền tệp (FILE)", "FILE")
        self._filter_combo.addItem("Tin nhắn (CHAT)", "CHAT")
        self._filter_combo.addItem("Đăng ký / Đăng nhập (AUTH)", "AUTH")
        self._filter_combo.addItem("Phiên kết nối (SESSION)", "SESSION")
        self._filter_combo.currentIndexChanged.connect(self._on_filter_combo_changed)
        filter_bar.addWidget(self._filter_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Tìm theo user, tên tệp, mã transfer…")
        self._search_edit.textChanged.connect(self._apply_table_filters)
        filter_bar.addWidget(self._search_edit, 1)

        self._btn_export = QPushButton("⬇ Xuất CSV")
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_clear = QPushButton("🧹 Xóa bảng")
        self._btn_clear.clicked.connect(self.clear_traces)
        filter_bar.addWidget(self._btn_export)
        filter_bar.addWidget(self._btn_clear)

        self._trace_table = QTableWidget(0, 7)
        self._trace_table.setHorizontalHeaderLabels(
            ["Thời gian", "Loại", "Thao tác", "Từ", "Đến", "Gói Chunk / Tệp", "Chi tiết"]
        )
        self._trace_table.verticalHeader().setVisible(False)
        self._trace_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._trace_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        th = self._trace_table.horizontalHeader()
        for col in (0, 1, 2, 3, 4):
            th.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self._trace_table.setColumnWidth(5, 210)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        trace_lay = QVBoxLayout(trace_box)
        trace_lay.addLayout(filter_bar)
        trace_lay.addWidget(self._trace_table, 1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_col)
        splitter.addWidget(trace_box)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 740])

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)
        root.addLayout(top_row)
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        self._wire_controller()

    # -------------------------------------------------------------- wiring
    def _wire_controller(self) -> None:
        s = self.server_ctrl
        s.server_started.connect(self._on_started)
        s.server_stopped.connect(self._on_stopped)
        s.server_error.connect(self._on_error)
        s.log_message.connect(self.append_log)
        s.directory_updated.connect(self._on_directory_updated)
        s.trace_recorded.connect(self._on_trace_recorded)
        s.message_count_changed.connect(self._on_message_count_changed)

    def _file_row(self, edit: QLineEdit, title: str, flt: str) -> QWidget:
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        btn = QPushButton("Chọn…")

        def _pick() -> None:
            path, _ = QFileDialog.getOpenFileName(self, title, "", f"{flt};;Tất cả (*)")
            if path:
                edit.setText(path)

        btn.clicked.connect(_pick)
        lay.addWidget(edit)
        lay.addWidget(btn)
        return row

    def _open_certgen(self) -> None:
        dlg = CertGenDialog(self)
        dlg.generated.connect(self._on_cert_generated)
        dlg.exec()

    def _on_cert_generated(self, cert: str, key: str) -> None:
        self._cert_edit.setText(cert)
        self._key_edit.setText(key)
        self._error_label.hide()

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

    # --------------------------------------------------------- server ctrl
    def _on_start(self) -> None:
        cfg = self.get_config()
        if not cfg["cert"] or not cfg["key"]:
            self._error_label.setText("Hãy chọn chứng chỉ và khóa riêng (hoặc bấm 'Tạo chứng chỉ TLS').")
            self._error_label.show()
            return
        self._error_label.hide()
        self._btn_start.setEnabled(False)
        self.append_log("Đang khởi chạy máy chủ…")
        self.server_ctrl.start_server(cfg)

    def _on_stop(self) -> None:
        clients = self.server_ctrl.client_count()
        if clients and QMessageBox.question(
            self,
            "Dừng máy chủ",
            f"Đang có {clients} client trực tuyến. Dừng máy chủ sẽ ngắt kết nối họ. Tiếp tục?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self._btn_stop.setEnabled(False)
        threading.Thread(target=self.server_ctrl.stop_server, name="lumichat-stop", daemon=True).start()

    def _on_started(self) -> None:
        self._set_running_ui(True)
        port = self.server_ctrl.tcp_port or self._port_spin.value()
        self._kpi_status.setText(f"Đang chạy (:{port})")
        self._kpi_status.setStyleSheet("color: #059669; font-size: 18px; font-weight: 800;")

    def _on_stopped(self) -> None:
        self._set_running_ui(False)
        self._kpi_status.setText("Đã dừng")
        self._kpi_status.setStyleSheet("color: #64748B; font-size: 18px; font-weight: 800;")
        self.append_log("Máy chủ đã dừng.")

    def _on_error(self, message: str) -> None:
        self._set_running_ui(False)
        self._error_label.setText(message)
        self._error_label.show()
        self._kpi_status.setText("Gặp lỗi")
        self._kpi_status.setStyleSheet("color: #DC2626; font-size: 18px; font-weight: 800;")
        self.append_log(f"Lỗi: {message}")

    def _set_running_ui(self, running: bool) -> None:
        self._btn_start.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        for w in (
            self._host_edit,
            self._port_spin,
            self._udp_spin,
            self._advertise_edit,
            self._cert_edit,
            self._key_edit,
            self._db_edit,
        ):
            w.setEnabled(not running)

    def append_log(self, text: str) -> None:
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_edit.append(f"[{stamp}] {sanitize(text)}")

    # --------------------------------------------------- directory & KPIs
    def _on_directory_updated(self, directory: list[dict]) -> None:
        self._directory = [dict(d) for d in directory if isinstance(d, dict)]
        n_on = self.online_user_count()
        n_off = self.offline_user_count()
        self._kpi_users.setText(f"{n_on} Online · {n_off} Offline")

        self._users_table.setRowCount(len(self._directory))
        for row, entry in enumerate(self._directory):
            uname = sanitize(entry.get("username"))
            online = bool(entry.get("online"))
            host, port = entry.get("host"), entry.get("port")
            addr = f"{sanitize(host)}:{port}" if online and host and port else "—"
            c_name = QTableWidgetItem(uname)
            c_state = QTableWidgetItem("● Trực tuyến" if online else "○ Ngoại tuyến")
            c_state.setForeground(QColor("#059669" if online else "#64748B"))
            c_addr = QTableWidgetItem(addr)
            self._users_table.setItem(row, 0, c_name)
            self._users_table.setItem(row, 1, c_state)
            self._users_table.setItem(row, 2, c_addr)

    def _on_message_count_changed(self, count: int) -> None:
        self._msg_count = int(count)
        self._kpi_msgs.setText(f"{self._msg_count} tin")

    def online_user_count(self) -> int:
        return sum(1 for d in self._directory if d.get("online"))

    def offline_user_count(self) -> int:
        return sum(1 for d in self._directory if not d.get("online"))

    # ------------------------------------------------------- trace history
    def _on_trace_recorded(self, event: dict) -> None:
        category = str(event.get("category", "INFO")).upper()
        action = str(event.get("action", ""))
        if action == "file_chunk":
            self._chunk_count += 1
            self._kpi_chunks.setText(f"{self._chunk_count} chunks")

        if self._trace_table.rowCount() >= _MAX_TRACE_ROWS:
            self._trace_table.removeRow(0)

        row = self._trace_table.rowCount()
        self._trace_table.insertRow(row)

        ts = sanitize(event.get("ts") or datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
        actor = sanitize(event.get("actor") or "—")
        target = sanitize(event.get("target") or "—")
        chunk_col, detail_col = self._format_trace_columns(action, event)

        cells = [ts, category, action, actor, target, chunk_col, detail_col]
        fg_hex, bg_hex = _CATEGORY_COLORS.get(category, ("#334155", "#F1F5F9"))
        for col, val in enumerate(cells):
            item = QTableWidgetItem(val)
            if col == 1:
                item.setForeground(QColor(fg_hex))
                item.setBackground(QColor(bg_hex))
            self._trace_table.setItem(row, col, item)

        self._trace_table.setRowHidden(row, not self._row_matches_filter(row))
        self._trace_table.scrollToBottom()

    @staticmethod
    def _format_trace_columns(action: str, event: dict) -> tuple[str, str]:
        tid_short = str(event.get("transfer_id") or "")[:8]
        fname = sanitize(event.get("filename") or "")
        if action == "file_chunk":
            idx = int(event.get("chunk_index", 0)) + 1
            total = int(event.get("total_chunks", 1))
            c_bytes = int(event.get("chunk_bytes", 0))
            relayed = int(event.get("bytes_relayed", 0))
            t_bytes = max(1, int(event.get("total_bytes", 1)))
            pct = int(relayed * 100 / t_bytes)
            return (
                f"Chunk {idx}/{total} · {fname}",
                f"[{tid_short}] +{human_size(c_bytes)} → Đã chuyển {human_size(relayed)}/{human_size(t_bytes)} ({pct}%)",
            )
        if action == "file_offer":
            return (
                f"{fname} ({event.get('total_chunks', 0)} chunks)",
                f"[{tid_short}] Khởi tạo gửi tệp ({human_size(int(event.get('size', 0)))})",
            )
        if action == "file_accept":
            return (
                f"{fname}",
                f"[{tid_short}] Sẵn sàng nhận luồng {event.get('total_chunks', 0)} chunk",
            )
        if action == "file_end":
            return (
                f"{fname}",
                f"[{tid_short}] Đã gửi đủ {event.get('total_chunks', 0)} chunk — chờ kiểm tra SHA-256",
            )
        if action == "file_ack":
            ok = bool(event.get("ok"))
            return (
                f"{fname}",
                f"[{tid_short}] {'Xác minh SHA-256 KHỚP — Hoàn tất' if ok else 'Lỗi xác minh: ' + sanitize(event.get('code'))}",
            )
        if action == "file_cancel":
            return (f"{fname}", f"[{tid_short}] Đã hủy ({sanitize(event.get('reason'))})")
        if action in {"chat_broadcast", "chat_direct", "chat_offline"}:
            mode = (
                "Lưu offline vào SQLite"
                if action == "chat_offline"
                else ("Tin nhắn chung" if action == "chat_broadcast" else "Tin nhắn riêng 1–1")
            )
            return ("—", f"{mode} ({event.get('chars', 0)} ký tự)")
        if action == "chat_history":
            return ("—", f"Đồng bộ {event.get('count', 0)} tin nhắn lịch sử")
        if action == "register":
            return ("—", "Đăng ký tài khoản mới")
        if action == "login":
            return ("—", "Đăng nhập TLS thành công")
        if action in {"logout", "disconnect"}:
            return ("—", "Đóng phiên kết nối")
        return (fname or "—", sanitize(event.get("detail") or action))

    def _on_filter_combo_changed(self) -> None:
        self._active_filter = str(self._filter_combo.currentData() or "ALL")
        self._apply_table_filters()

    def set_trace_filter(self, category: str) -> None:
        cat = category.upper()
        self._active_filter = cat
        for i in range(self._filter_combo.count()):
            if self._filter_combo.itemData(i) == cat:
                self._filter_combo.blockSignals(True)
                self._filter_combo.setCurrentIndex(i)
                self._filter_combo.blockSignals(False)
                break
        self._apply_table_filters()

    def _row_matches_filter(self, row: int) -> bool:
        cat_item = self._trace_table.item(row, 1)
        cat = cat_item.text() if cat_item is not None else ""
        if self._active_filter != "ALL" and cat != self._active_filter:
            return False
        query = self._search_edit.text().strip().lower()
        if not query:
            return True
        for col in range(self._trace_table.columnCount()):
            cell = self._trace_table.item(row, col)
            if cell is not None and query in cell.text().lower():
                return True
        return False

    def _apply_table_filters(self) -> None:
        for row in range(self._trace_table.rowCount()):
            self._trace_table.setRowHidden(row, not self._row_matches_filter(row))

    def clear_traces(self) -> None:
        self._trace_table.setRowCount(0)
        self._chunk_count = 0
        self._kpi_chunks.setText("0 chunks")

    def trace_row_count(self) -> int:
        return self._trace_table.rowCount()

    def visible_trace_row_count(self) -> int:
        return sum(
            1 for r in range(self._trace_table.rowCount()) if not self._trace_table.isRowHidden(r)
        )

    def _export_csv(self) -> None:  # pragma: no cover - interactive file dialog
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất bảng Trace ra CSV", "lumichat_trace.csv", "CSV (*.csv)"
        )
        if not path:
            return
        headers = [
            self._trace_table.horizontalHeaderItem(c).text()
            for c in range(self._trace_table.columnCount())
        ]
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for r in range(self._trace_table.rowCount()):
                writer.writerow(
                    [
                        (self._trace_table.item(r, c).text() if self._trace_table.item(r, c) else "")
                        for c in range(self._trace_table.columnCount())
                    ]
                )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.server_ctrl.is_running() and self.server_ctrl.client_count():
            if (
                QMessageBox.question(
                    self,
                    "Đóng Server Console",
                    "Server đang có người dùng kết nối. Dừng server và đóng cửa sổ?",
                )
                != QMessageBox.StandardButton.Yes
            ):
                event.ignore()
                return
        self.server_ctrl.stop_server()
        event.accept()
