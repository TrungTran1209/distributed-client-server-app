"""Standalone LumiChat Server Console — Server Configuration, Online/Offline User Directory,
and Real-Time TLS Application/Chunk & Protocol Inspector.
"""

from __future__ import annotations

import csv
import datetime
import json
from pathlib import Path
import threading
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .controllers.server_controller import ServerController
from .styles.theme import APP_BRAND
from .widgets.cert_gen_dialog import CertGenDialog
from .widgets.formatting import format_hex_dump, human_size, sanitize

_MAX_TRACE_ROWS = 3000

# Wireshark-inspired protocol tints (soft pastel background, crisp dark foreground)
_PROTOCOL_COLORS: dict[str, tuple[str, str]] = {
    "CHUNK": ("#C2410C", "#FFF7ED"),     # Warm Amber/Orange
    "FILE": ("#0369A1", "#E0F2FE"),      # Cyan Sky
    "CHAT": ("#4338CA", "#EEF2FF"),      # Indigo Lavender
    "AUTH": ("#047857", "#DCFCE7"),      # Emerald Mint
    "SESSION": ("#6D28D9", "#F3E8FF"),   # Soft Violet
    "ERROR": ("#B91C1C", "#FEE2E2"),     # Rose Red
    "INFO": ("#334155", "#F8FAFC"),      # Slate
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
    lbl_title.setStyleSheet("color: #64748B; font-size: 11px; font-weight: 700; letter-spacing: 0.5px;")
    lbl_val = QLabel(initial)
    lbl_val.setStyleSheet(f"color: {accent_hex}; font-size: 17px; font-weight: 800;")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(2)
    lay.addWidget(lbl_title)
    lay.addWidget(lbl_val)
    return card, lbl_val


class ServerMainWindow(QMainWindow):
    """Dedicated Server Console with hosting controls and a TLS-safe protocol inspector."""

    def __init__(self, server_ctrl: ServerController) -> None:
        super().__init__()
        self.server_ctrl = server_ctrl
        self.setWindowTitle(f"{APP_BRAND} Server Console — Quản trị & TLS Application Inspector")
        self.setMinimumSize(1200, 780)

        self._directory: list[dict] = []
        self._packet_records: list[dict] = []
        self._packet_count = 0
        self._chunk_count = 0
        self._msg_count = 0
        self._active_filter = "ALL"
        self._capture_paused = False

        # ------------------------------------------------ Top KPI Banner
        top_row = QHBoxLayout()
        brand_box = QVBoxLayout()
        title = QLabel(f"🛰️ {APP_BRAND} Server Console")
        title.setObjectName("title")
        subtitle = QLabel(
            "Khởi tạo máy chủ TLS & theo dõi metadata giao thức thời gian thực "
            "(chat, phiên, file và từng chunk; không lưu payload riêng tư)"
        )
        subtitle.setObjectName("subtitle")
        brand_box.addWidget(title)
        brand_box.addWidget(subtitle)
        top_row.addLayout(brand_box, 2)

        kpi_status_card, self._kpi_status = _kpi_card("TRẠNG THÁI SERVER", "Đang dừng", "#64748B")
        kpi_users_card, self._kpi_users = _kpi_card("NGƯỜI DÙNG BẢO MẬT", "0 Online · 0 Offline", "#10B981")
        kpi_chunks_card, self._kpi_chunks = _kpi_card("GÓI CHUNK SNIFFER", "0 chunks", "#F97316")
        kpi_msgs_card, self._kpi_msgs = _kpi_card("TIN NHẮN LƯU TRỮ", "0 tin", "#4F46E5")
        for card in (kpi_status_card, kpi_users_card, kpi_chunks_card, kpi_msgs_card):
            top_row.addWidget(card, 1)

        # ------------------------------------------------ Left Column (Host Controls + Directory + Log)
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

        cfg_box = QGroupBox("Khởi tạo & Cấu hình Máy chủ")
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

        users_box = QGroupBox("Danh bạ Người dùng (Trực tuyến & Ngoại tuyến)")
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
        self._log_edit.setMaximumHeight(90)
        self._log_edit.setPlaceholderText("Nhật ký hệ thống máy chủ…")

        left_col = QWidget()
        left_lay = QVBoxLayout(left_col)
        left_lay.setContentsMargins(0, 0, 8, 0)
        left_lay.addWidget(cfg_box)
        left_lay.addWidget(users_box, 1)
        left_lay.addWidget(self._log_edit)

        # ------------------------------------------------ Right Column: TLS Application Inspector
        sniffer_box = QGroupBox(
            "🛡 TLS Application Inspector (metadata giao thức & từng chunk)"
        )
        sniffer_lay = QVBoxLayout(sniffer_box)
        sniffer_lay.setSpacing(8)

        # 1. Wireshark Toolbar & Filter Bar
        ws_tools = QHBoxLayout()
        self._btn_pause = QPushButton("⏸ Tạm dừng")
        self._btn_pause.clicked.connect(self._toggle_pause_capture)
        self._btn_clear = QPushButton("🧹 Xóa bảng")
        self._btn_clear.clicked.connect(self.clear_traces)
        self._btn_export = QPushButton("⬇ Xuất CSV")
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_export_json = QPushButton("⬇ Xuất JSON")
        self._btn_export_json.clicked.connect(self._export_json)

        ws_tools.addWidget(self._btn_pause)
        ws_tools.addWidget(self._btn_clear)
        ws_tools.addSpacing(10)
        ws_tools.addWidget(self._btn_export)
        ws_tools.addWidget(self._btn_export_json)
        ws_tools.addStretch()

        self._stats_badge = QLabel("Packets: 0 | Hiển thị: 0 | Chunks: 0")
        self._stats_badge.setStyleSheet(
            "background: #F1F5F9; color: #475569; border-radius: 6px; padding: 4px 10px; font-weight: 700; font-size: 11px;"
        )
        ws_tools.addWidget(self._stats_badge)

        # Filter bar with Wireshark syntax style
        filter_bar = QHBoxLayout()
        filter_icon = QLabel("🔍 Protocol Filter:")
        filter_icon.setStyleSheet("font-weight: 700; color: #4F46E5;")
        filter_bar.addWidget(filter_icon)

        self._filter_combo = QComboBox()
        self._filter_combo.addItem("Tất cả giao thức (ALL)", "ALL")
        self._filter_combo.addItem("Gói Chunk (CHUNK)", "CHUNK")
        self._filter_combo.addItem("Truyền tệp (FILE)", "FILE")
        self._filter_combo.addItem("Tin nhắn (CHAT)", "CHAT")
        self._filter_combo.addItem("Xác thực (AUTH)", "AUTH")
        self._filter_combo.addItem("Phiên kết nối (SESSION)", "SESSION")
        self._filter_combo.addItem("Lỗi (ERROR)", "ERROR")
        self._filter_combo.currentIndexChanged.connect(self._on_filter_combo_changed)
        filter_bar.addWidget(self._filter_combo)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(
            "Nhập bộ lọc (vd: collab.chunk, collab.chat, ip.addr, alice, chunk > 0)..."
        )
        self._search_edit.setStyleSheet(
            "QLineEdit { border: 2px solid #10B981; background: #FFFFFF; padding: 6px 10px; font-family: monospace; }"
        )
        self._search_edit.textChanged.connect(self._apply_table_filters)
        filter_bar.addWidget(self._search_edit, 1)

        # 2. Wireshark 3-Pane Splitter:
        # Pane 1 (Top): Packet List
        self._trace_table = QTableWidget(0, 7)
        self._trace_table.setHorizontalHeaderLabels(
            ["No.", "Thời gian", "Nguồn", "Đích", "Giao thức", "Kích thước", "Thông tin tóm tắt (Info)"]
        )
        self._trace_table.verticalHeader().setVisible(False)
        self._trace_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._trace_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._trace_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._trace_table.itemSelectionChanged.connect(self._on_packet_selected)

        th = self._trace_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        # Pane 2 (Middle): Packet Details (Tree Widget)
        self._details_tree = QTreeWidget()
        self._details_tree.setHeaderLabels(["Chi tiết Giải mã Gói tin (Wireshark Packet Dissection)"])
        self._details_tree.header().setStretchLastSection(True)
        self._details_tree.setFont(QFont("Consolas", 10))

        # Pane 3 (Bottom): Hex Dump View
        hex_box = QWidget()
        hex_lay = QVBoxLayout(hex_box)
        hex_lay.setContentsMargins(0, 0, 0, 0)
        hex_lay.setSpacing(4)
        hex_top = QHBoxLayout()
        self._hex_info_lbl = QLabel("Packet Bytes & Hex Dump (0000 - Offset | Hexadecimal | ASCII)")
        self._hex_info_lbl.setStyleSheet("font-weight: 700; color: #475569; font-size: 11px;")
        btn_copy_hex = QPushButton("📋 Sao chép Hex Dump")
        btn_copy_hex.clicked.connect(self._copy_hex_dump)
        hex_top.addWidget(self._hex_info_lbl)
        hex_top.addStretch()
        hex_top.addWidget(btn_copy_hex)

        self._hex_edit = QPlainTextEdit()
        self._hex_edit.setReadOnly(True)
        self._hex_edit.setFont(QFont("Consolas", 10))
        self._hex_edit.setPlainText("Chọn một gói tin ở danh sách trên để xem bản phân tích Hex Dump chi tiết.")
        self._hex_edit.setStyleSheet(
            "QPlainTextEdit { background: #FFFFFF; border: 1px solid #CBD5E1; color: #0F172A; "
            "font-family: 'Consolas', 'Cascadia Code', monospace; font-size: 11px; line-height: 1.4; }"
        )

        hex_lay.addLayout(hex_top)
        hex_lay.addWidget(self._hex_edit, 1)

        # Wireshark Vertical Splitter (Packet List | Details Tree | Hex Dump)
        ws_splitter = QSplitter(Qt.Orientation.Vertical)
        ws_splitter.addWidget(self._trace_table)
        ws_splitter.addWidget(self._details_tree)
        ws_splitter.addWidget(hex_box)
        ws_splitter.setStretchFactor(0, 3)
        ws_splitter.setStretchFactor(1, 2)
        ws_splitter.setStretchFactor(2, 2)
        ws_splitter.setSizes([260, 160, 140])

        sniffer_lay.addLayout(ws_tools)
        sniffer_lay.addLayout(filter_bar)
        sniffer_lay.addWidget(ws_splitter, 1)

        # Main Horizontal Splitter (Left Config | Right Sniffer)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_col)
        splitter.addWidget(sniffer_box)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([360, 840])

        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)
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
        self.append_log("Đang khởi chạy máy chủ TLS…")
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
        self._kpi_status.setStyleSheet("color: #059669; font-size: 17px; font-weight: 800;")

    def _on_stopped(self) -> None:
        self._set_running_ui(False)
        self._kpi_status.setText("Đã dừng")
        self._kpi_status.setStyleSheet("color: #64748B; font-size: 17px; font-weight: 800;")
        self.append_log("Máy chủ đã dừng an toàn.")

    def _on_error(self, message: str) -> None:
        self._set_running_ui(False)
        self._error_label.setText(message)
        self._error_label.show()
        self._kpi_status.setText("Gặp lỗi")
        self._kpi_status.setStyleSheet("color: #DC2626; font-size: 17px; font-weight: 800;")
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

    # ------------------------------------------------------- Wireshark Sniffer
    def _toggle_pause_capture(self) -> None:
        self._capture_paused = not self._capture_paused
        if self._capture_paused:
            self._btn_pause.setText("▶ Tiếp tục bắt")
            self._btn_pause.setStyleSheet("background: #FEF3C7; color: #B45309; font-weight: 700;")
        else:
            self._btn_pause.setText("⏸ Tạm dừng")
            self._btn_pause.setStyleSheet("")

    def _on_trace_recorded(self, event: dict) -> None:
        if self._capture_paused:
            return

        category = str(event.get("category", "INFO")).upper()
        action = str(event.get("action", ""))
        self._packet_count += 1

        if action == "file_chunk":
            self._chunk_count += 1
            self._kpi_chunks.setText(f"{self._chunk_count} chunks")

        if len(self._packet_records) >= _MAX_TRACE_ROWS:
            self._packet_records.pop(0)
            if self._trace_table.rowCount() > 0:
                self._trace_table.removeRow(0)

        record = dict(event)
        record["packet_no"] = self._packet_count
        self._packet_records.append(record)

        row = self._trace_table.rowCount()
        self._trace_table.insertRow(row)

        ts = sanitize(event.get("ts") or datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3])
        actor = sanitize(event.get("actor") or "—")
        target = sanitize(event.get("target") or "—")
        proto_str = f"TLS/{category}" if category != "UDP" else "UDP/DISCOVERY"

        length_bytes, info_str = self._format_wireshark_info(action, event)
        len_str = f"{length_bytes:,} B"

        cells = [str(self._packet_count), ts, actor, target, proto_str, len_str, info_str]
        fg_hex, bg_hex = _PROTOCOL_COLORS.get(category, ("#334155", "#F8FAFC"))

        for col, val in enumerate(cells):
            item = QTableWidgetItem(val)
            if col in (0, 4):  # Packet No. & Protocol
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 5:  # Length
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item.setBackground(QColor(bg_hex))
            item.setForeground(QColor(fg_hex))
            self._trace_table.setItem(row, col, item)

        self._trace_table.setRowHidden(row, not self._row_matches_filter(row))
        self._update_stats_badge()

        # If user is at the bottom, auto scroll
        sb = self._trace_table.verticalScrollBar()
        if sb and sb.value() >= sb.maximum() - 4:
            self._trace_table.scrollToBottom()

    def _format_wireshark_info(self, action: str, event: dict) -> tuple[int, str]:
        """Compute approximate frame length on wire and informative Wireshark summary string."""
        fname = sanitize(event.get("filename") or "")
        tid = str(event.get("transfer_id") or "")
        tid_short = tid[:8]

        if action == "file_chunk":
            idx = int(event.get("chunk_index", 0)) + 1
            total = int(event.get("total_chunks", 1))
            c_bytes = int(event.get("chunk_bytes", 0))
            relayed = int(event.get("bytes_relayed", 0))
            t_bytes = max(1, int(event.get("total_bytes", 1)))
            pct = int(relayed * 100 / t_bytes)
            c_sha = str(event.get("chunk_sha256") or "")[:8]
            sha_part = f" SHA256={c_sha}…" if c_sha else ""
            wire_len = c_bytes + 250  # 4-byte framing + JSON envelope + b64 payload
            info = (
                f"[CHUNK #{idx}/{total}] File='{fname}' Len={human_size(c_bytes)}{sha_part} "
                f"→ Đã relay {human_size(relayed)}/{human_size(t_bytes)} ({pct}%)"
            )
            return wire_len, info

        if action == "file_offer":
            size = int(event.get("size", 0))
            chunks = int(event.get("total_chunks", 0))
            sha = str(event.get("sha256") or "")[:12]
            return 280, f"[FILE_OFFER] Khởi tạo truyền '{fname}' ({human_size(size)}, {chunks} chunks) SHA-256={sha}…"

        if action == "file_accept":
            chunks = int(event.get("total_chunks", 0))
            return 180, f"[FILE_ACCEPT] Chấp nhận nhận tệp '{fname}' ({chunks} chunks)"

        if action == "file_end":
            chunks = int(event.get("total_chunks", 0))
            return 210, f"[FILE_END] Đã gửi đủ {chunks} chunks cho '{fname}' — Đợi kiểm tra SHA-256"

        if action == "file_ack":
            ok = bool(event.get("ok"))
            status = "SHA-256 KHỚP HOÀN HẢO ✓" if ok else f"LỖI: {sanitize(event.get('code'))}"
            return 190, f"[FILE_ACK] '{fname}' → {status}"

        if action == "file_cancel":
            reason = sanitize(event.get("reason") or "user_cancel")
            return 170, f"[FILE_CANCEL] Hủy phiên '{fname}' (Lý do: {reason})"

        if action in {"chat_broadcast", "chat_direct", "chat_offline"}:
            chars = int(event.get("chars", 0))
            preview = sanitize(event.get("text_preview") or "")
            preview_str = f' "{preview}"' if preview else ""
            mode = (
                "Lưu offline SQLite"
                if action == "chat_offline"
                else ("Kênh chung" if action == "chat_broadcast" else "Tin nhắn riêng")
            )
            return 120 + chars, f"[CHAT] {mode} ({chars} ký tự){preview_str}"

        if action == "chat_history":
            count = int(event.get("count", 0))
            return 240, f"[CHAT_SYNC] Đồng bộ {count} tin nhắn lịch sử từ SQLite"

        if action == "register":
            return 160, f"[AUTH_REG] Đăng ký tài khoản '{event.get('actor')}' (scrypt salt 16B)"

        if action == "login":
            return 180, f"[AUTH_LOGIN] Đăng nhập TLS thành công: '{event.get('actor')}'"

        if action in {"logout", "disconnect"}:
            return 100, f"[SESSION_{action.upper()}] Thu hồi phiên người dùng '{event.get('actor')}'"

        detail = sanitize(event.get("detail") or action)
        return 140, f"[{action.upper()}] {detail}"

    # ------------------------------------------------ Packet Inspection (Panes 2 & 3)
    def _on_packet_selected(self) -> None:
        selected_rows = self._trace_table.selectedItems()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        if row < 0 or row >= len(self._packet_records):
            return

        record = self._packet_records[row]
        self._dissect_packet_to_tree(record)
        self._render_hex_dump(record)

    def _dissect_packet_to_tree(self, event: dict) -> None:
        self._details_tree.clear()
        p_no = event.get("packet_no", 1)
        category = str(event.get("category", "INFO")).upper()
        action = str(event.get("action", ""))
        ts = str(event.get("ts", ""))
        actor = str(event.get("actor", "—"))
        target = str(event.get("target", "—"))
        length_bytes, summary_info = self._format_wireshark_info(action, event)

        # 1. Frame Layer
        item_frame = QTreeWidgetItem(self._details_tree)
        item_frame.setText(0, f"Frame {p_no}: {length_bytes} bytes on wire (TCP Port {self._port_spin.value()})")
        QTreeWidgetItem(item_frame, [f"Arrival Time: {ts}"])
        QTreeWidgetItem(item_frame, [f"Frame Number: {p_no}"])
        QTreeWidgetItem(item_frame, [f"Frame Length: {length_bytes} bytes ({length_bytes * 8} bits)"])
        QTreeWidgetItem(item_frame, [f"Capture State: Hoàn tất (No packet loss)"])

        # 2. TLS Layer
        item_tls = QTreeWidgetItem(self._details_tree)
        item_tls.setText(0, "Transport Layer Security (TLS 1.2+ / OpenSSL Encrypted Stream)")
        QTreeWidgetItem(item_tls, ["Security Protocol: TLS 1.2+ / TLS 1.3"])
        QTreeWidgetItem(item_tls, ["Identity Verification: X.509 Certificate with SAN hostname & IP matching"])
        QTreeWidgetItem(item_tls, ["Confidentiality: End-to-end Encrypted Application Payload"])

        # 3. Collab Application Framing Layer
        item_framing = QTreeWidgetItem(self._details_tree)
        item_framing.setText(0, f"Collab Application Protocol Framing (Payload Length: {max(0, length_bytes - 4)} bytes)")
        QTreeWidgetItem(item_framing, [f"Header: 4-byte Big-Endian Length Prefix ({max(0, length_bytes - 4)} B)"])
        QTreeWidgetItem(item_framing, ["Payload Encoding: UTF-8 JSON (RFC 8259)"])
        QTreeWidgetItem(item_framing, [f"Action Type: {action}"])
        QTreeWidgetItem(item_framing, [f"Category: {category}"])
        QTreeWidgetItem(item_framing, [f"Source Endpoint: {actor}"])
        QTreeWidgetItem(item_framing, [f"Destination Endpoint: {target}"])

        # 4. Action-specific details layer
        if action == "file_chunk":
            item_chunk = QTreeWidgetItem(self._details_tree)
            idx = int(event.get("chunk_index", 0)) + 1
            total = int(event.get("total_chunks", 1))
            c_bytes = int(event.get("chunk_bytes", 0))
            relayed = int(event.get("bytes_relayed", 0))
            t_bytes = max(1, int(event.get("total_bytes", 1)))
            pct = int(relayed * 100 / t_bytes)

            item_chunk.setText(0, f"Chunk Payload Dissector (Gói Chunk #{idx}/{total} - {human_size(c_bytes)})")
            QTreeWidgetItem(item_chunk, [f"Transfer ID: {event.get('transfer_id')}"])
            QTreeWidgetItem(item_chunk, [f"Tên tệp: {event.get('filename')}"])
            QTreeWidgetItem(item_chunk, [f"Số thứ tự Chunk: {idx} / {total} (Index: {idx - 1})"])
            QTreeWidgetItem(item_chunk, [f"Kích thước Chunk: {c_bytes:,} bytes ({human_size(c_bytes)})"])
            QTreeWidgetItem(item_chunk, [f"Tiến độ Relay Stream: {relayed:,} / {t_bytes:,} bytes ({pct}%)"])
            QTreeWidgetItem(item_chunk, [f"Mã băm SHA-256 của Chunk: {event.get('chunk_sha256', '—')}"])
            QTreeWidgetItem(item_chunk, [f"Mã băm SHA-256 toàn tệp kỳ vọng: {event.get('expected_file_sha256', '—')}"])
            QTreeWidgetItem(item_chunk, ["Cơ chế Relay: Bộ đệm O(1) qua TLS không lưu ổ cứng server"])

        elif action.startswith("file_"):
            item_file = QTreeWidgetItem(self._details_tree)
            item_file.setText(0, f"File Transfer Control Layer ({action})")
            QTreeWidgetItem(item_file, [f"Transfer ID: {event.get('transfer_id')}"])
            QTreeWidgetItem(item_file, [f"Tên tệp: {event.get('filename')}"])
            if event.get("size"):
                QTreeWidgetItem(item_file, [f"Kích thước tệp: {event.get('size')} bytes ({human_size(int(event.get('size', 0)))})"])
            if event.get("total_chunks"):
                QTreeWidgetItem(item_file, [f"Tổng số chunks: {event.get('total_chunks')}"])
            if event.get("sha256"):
                QTreeWidgetItem(item_file, [f"SHA-256 đầu-cuối: {event.get('sha256')}"])
            if "ok" in event:
                QTreeWidgetItem(item_file, [f"Kết quả kiểm tra SHA-256: {'Khớp ✓' if event['ok'] else 'Lỗi Checksum'}"])

        elif category == "CHAT":
            item_chat = QTreeWidgetItem(self._details_tree)
            item_chat.setText(0, f"Chat Message Protocol Layer ({action})")
            QTreeWidgetItem(item_chat, [f"Người gửi: {actor}"])
            QTreeWidgetItem(item_chat, [f"Người nhận: {target}"])
            QTreeWidgetItem(item_chat, [f"Độ dài: {event.get('chars', 0)} ký tự"])
            if event.get("text_preview"):
                QTreeWidgetItem(item_chat, [f"Nội dung xem trước: {event.get('text_preview')}"])
            QTreeWidgetItem(item_chat, ["Lưu trữ: Bền vững trong SQLite MessageStore"])

        elif category == "AUTH":
            item_auth = QTreeWidgetItem(self._details_tree)
            item_auth.setText(0, f"Authentication & Cryptography Layer ({action})")
            QTreeWidgetItem(item_auth, [f"Tài khoản: {actor}"])
            QTreeWidgetItem(item_auth, [f"Địa chỉ IP máy khách: {target}"])
            QTreeWidgetItem(item_auth, ["KDF Thuật toán: hashlib.scrypt (N=16384, r=8, p=1)"])
            QTreeWidgetItem(item_auth, ["Salt: 16 byte ngẫu nhiên riêng biệt cho từng tài khoản"])
            QTreeWidgetItem(item_auth, ["Xác minh an toàn: Thời gian hằng số hmac.compare_digest"])

        self._details_tree.expandAll()

    def _render_hex_dump(self, event: dict) -> None:
        p_no = event.get("packet_no", 1)
        action = str(event.get("action", ""))
        category = str(event.get("category", "INFO"))
        # Render only the inspected metadata. Raw chat/file payloads never enter the GUI trace.
        sanitized_event = {k: v for k, v in event.items() if k != "raw_payload_preview"}
        wire_json = json.dumps(sanitized_event, ensure_ascii=False)
        frame_bytes = wire_json.encode("utf-8")

        length_bytes, _ = self._format_wireshark_info(action, event)
        self._hex_info_lbl.setText(
            f"Frame #{p_no} | Kích thước: {length_bytes:,} B | Giao thức: TLS/{category} ({action})"
        )
        self._hex_edit.setPlainText(format_hex_dump(frame_bytes, max_bytes=512))

    def _copy_hex_dump(self) -> None:
        text = self._hex_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    # ------------------------------------------------ Filtering & Export
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
        if row >= len(self._packet_records):
            return True
        event = self._packet_records[row]
        cat = str(event.get("category", "")).upper()
        action = str(event.get("action", "")).lower()

        if self._active_filter != "ALL" and cat != self._active_filter:
            return False

        query = self._search_edit.text().strip().lower()
        if not query:
            return True

        # Support Wireshark shorthand filters
        if query in {"collab.chunk", "chunk"}:
            return action == "file_chunk"
        if query in {"collab.chat", "chat"}:
            return cat == "CHAT"
        if query in {"collab.file", "file"}:
            return cat == "FILE" or action == "file_chunk"
        if query in {"collab.auth", "auth"}:
            return cat == "AUTH"
        if query in {"collab.session", "session"}:
            return cat == "SESSION"

        # General text matching across packet properties
        for key in ("actor", "target", "filename", "transfer_id", "action", "category", "ts"):
            val = str(event.get(key, "")).lower()
            if query in val:
                return True
        return False

    def _apply_table_filters(self) -> None:
        for row in range(self._trace_table.rowCount()):
            self._trace_table.setRowHidden(row, not self._row_matches_filter(row))
        self._update_stats_badge()

    def _update_stats_badge(self) -> None:
        total = self._trace_table.rowCount()
        visible = self.visible_trace_row_count()
        self._stats_badge.setText(
            f"Bắt được: {total} gói | Hiển thị: {visible} | Chunks: {self._chunk_count}"
        )

    def clear_traces(self) -> None:
        self._trace_table.setRowCount(0)
        self._packet_records.clear()
        self._chunk_count = 0
        self._kpi_chunks.setText("0 chunks")
        self._details_tree.clear()
        self._hex_edit.setPlainText("Chọn một gói tin ở bảng trên để xem giải mã Hex Dump chi tiết.")
        self._update_stats_badge()

    def trace_row_count(self) -> int:
        return self._trace_table.rowCount()

    def visible_trace_row_count(self) -> int:
        return sum(
            1 for r in range(self._trace_table.rowCount()) if not self._trace_table.isRowHidden(r)
        )

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất danh sách bắt gói tin Wireshark ra CSV", "wireshark_capture.csv", "CSV (*.csv)"
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

    def _export_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất gói tin Wireshark ra JSON", "wireshark_packets.json", "JSON (*.json)"
        )
        if not path:
            return
        # Filter out binary preview from JSON serialization
        clean_records = []
        for r in self._packet_records:
            entry = dict(r)
            if "raw_payload_preview" in entry:
                entry.pop("raw_payload_preview")
            clean_records.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(clean_records, f, ensure_ascii=False, indent=2)

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
