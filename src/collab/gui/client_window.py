"""Standalone LumiChat Client Window — Connect, Auth, Online/Offline Directory,
Persistent Chat History, and Zero-Prompt Automatic File Transfer.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
)

from collab.common.tls import create_client_context

from .controllers.client_controller import ClientController
from .styles.theme import APP_BRAND
from .views.auth_view import AuthView
from .views.chat_view import ChatView
from .views.connect_view import ConnectView
from .widgets.formatting import describe_transfer_error
from .widgets.transfer_manager import TransferManagerWidget

_CLIENT_PAGES = ("connect", "auth", "chat")


class ClientMainWindow(QMainWindow):
    """Pure client desktop window (no server-hosting screens, no file-offer accept modal)."""

    def __init__(self, client_ctrl: ClientController | None = None) -> None:
        super().__init__()
        self.client_ctrl = client_ctrl or ClientController(auto_accept=True)
        self.setWindowTitle(f"{APP_BRAND} — Trò chuyện & Chia sẻ tệp nhanh")
        self.setMinimumSize(1040, 680)
        self._endpoint: tuple[str, int, str, str] | None = None
        self._download_root = Path("downloads")
        self._register_user = ""
        self._last_username = ""

        self.connect_view = ConnectView()
        self.connect_view._btn_back.hide()  # Client starts directly on Connect
        self.auth_view = AuthView()
        self.chat_view = ChatView()

        self._stack = QStackedWidget()
        for view in (self.connect_view, self.auth_view, self.chat_view):
            self._stack.addWidget(view)
        self.setCentralWidget(self._stack)

        self.transfer_manager = TransferManagerWidget()
        self._dock = QDockWidget("Lịch sử tệp", self)
        self._dock.setWidget(self.transfer_manager)
        self._dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()

        self._conn_label = QLabel("Chưa kết nối máy chủ")
        self.statusBar().addPermanentWidget(self._conn_label)

        self._wire_views()
        self._wire_client()
        self.show_connect()

    # ---------------------------------------------------------- navigation
    def _show(self, name: str) -> None:
        self._stack.setCurrentIndex(_CLIENT_PAGES.index(name))

    def current_page(self) -> str:
        return _CLIENT_PAGES[self._stack.currentIndex()]

    def show_connect(self) -> None:
        self._show("connect")

    def show_auth(self) -> None:
        self._show("auth")

    def show_chat(self) -> None:
        self._show("chat")

    # -------------------------------------------------------------- wiring
    def _wire_views(self) -> None:
        self.connect_view.connect_requested.connect(self._begin_connect)
        self.connect_view.discover_requested.connect(self._discover)
        self.auth_view.back_requested.connect(self._cancel_auth)
        self.auth_view.login_requested.connect(self._login)
        self.auth_view.register_requested.connect(self._register)
        self.chat_view.send_requested.connect(lambda text, to: self.client_ctrl.send_chat(to, text))
        self.chat_view.file_send_requested.connect(self.client_ctrl.send_file)
        self.chat_view.logout_requested.connect(self._logout)
        self.chat_view.disconnect_logout_requested.connect(self._disconnect_to_connect_page)
        self.chat_view.transfers_panel_requested.connect(
            lambda: self._dock.setVisible(not self._dock.isVisible())
        )
        self.chat_view.reconnect_requested.connect(self._reconnect)
        self.transfer_manager.cancel_requested.connect(self._confirm_cancel)
        self.transfer_manager.download_requested.connect(self.client_ctrl.accept_file)
        self.chat_view.file_download_requested.connect(self.client_ctrl.accept_file)
        self.chat_view._users.recipient_changed.connect(self.transfer_manager.set_conversation)

    def _wire_client(self) -> None:
        c = self.client_ctrl
        c.connected.connect(self._on_connected)
        c.connection_lost.connect(self._on_connection_lost)
        c.discovery_finished.connect(self._on_discovery_finished)
        c.discovery_failed.connect(self._on_discovery_failed)
        c.auth_succeeded.connect(self._on_auth_succeeded)
        c.auth_failed.connect(self._on_auth_failed)
        c.register_finished.connect(self._on_register_finished)
        c.transfer_offer.connect(self._on_transfer_offer)
        c.directory_updated.connect(self.chat_view.set_directory)
        c.history_loaded.connect(self.chat_view.load_history)
        c.message_received.connect(self.chat_view.add_message)
        c.chat_sent.connect(self._on_chat_sent)
        c.chat_queued_offline.connect(self.chat_view.show_offline_queued_notice)
        c.chat_failed.connect(self.chat_view.show_error)
        c.transfer_started.connect(self._on_transfer_started)
        c.transfer_progress.connect(
            lambda p: self.transfer_manager.update_progress(p.transfer_id, p)
        )
        c.transfer_done.connect(self._on_transfer_done)
        c.transfer_error.connect(self._on_transfer_error)

    # ------------------------------------------------------------- connect
    def _begin_connect(self, host: str, port: int, ca: str, download_dir: str) -> None:
        if ca and not os.path.isfile(ca):
            self.connect_view.set_error(f"Không tìm thấy file chứng chỉ CA: {ca}")
            return
        try:
            ctx = create_client_context(ca or None)
        except Exception as exc:  # noqa: BLE001
            self.connect_view.set_error(f"Không đọc được chứng chỉ CA: {exc}")
            return
        self._endpoint = (host, port, ca, download_dir)
        self._download_root = Path(download_dir).expanduser()
        self.connect_view.clear_error()
        self.connect_view.set_connecting(True)
        self._conn_label.setText(f"Đang kết nối tới {host}:{port}…")
        os.makedirs(download_dir, exist_ok=True)
        self.client_ctrl.connect_to_server(host, port, ctx, download_dir)

    def _reconnect(self) -> None:
        if self._endpoint is None:
            self.show_connect()
            return
        self.chat_view._btn_reconnect.setEnabled(False)
        self._begin_connect(*self._endpoint)

    def _discover(self, udp_port: int) -> None:
        self.connect_view.clear_discovered()
        self.connect_view.clear_error()
        self.connect_view.set_discovering(True)
        broadcast = self.connect_view.broadcast_enabled()
        self.client_ctrl.discover(
            udp_port, broadcast, "255.255.255.255" if broadcast else "127.0.0.1"
        )

    def _on_discovery_finished(self, info) -> None:
        self.connect_view.set_discovering(False)
        if info is None:
            self.connect_view.set_error(
                "Không tìm thấy máy chủ nào. Kiểm tra máy chủ đang chạy, cổng UDP và mạng LAN."
            )
        else:
            self.connect_view.add_discovered_server(info)

    def _on_discovery_failed(self, message: str) -> None:
        self.connect_view.set_discovering(False)
        self.connect_view.set_error(f"Dò tìm thất bại: {message}")

    def _on_connected(self, _welcome: dict) -> None:
        self.connect_view.set_connecting(False)
        self.chat_view._btn_reconnect.setEnabled(True)
        host, port = self._endpoint[:2] if self._endpoint else ("?", 0)
        self._conn_label.setText(f"🟢 Đã kết nối {host}:{port} (TLS)")
        self.auth_view.clear_error()
        self.auth_view.set_loading(False)
        if self._last_username:
            self.auth_view.clear_fields()
            self.auth_view.show_login_tab(self._last_username)
            self.auth_view.set_info("Đã kết nối lại máy chủ — vui lòng nhập mật khẩu để đăng nhập.")
        self.show_auth()

    def _on_connection_lost(self, reason: str) -> None:
        self.connect_view.set_connecting(False)
        self.chat_view._btn_reconnect.setEnabled(True)
        self._conn_label.setText("🔴 Mất kết nối")
        if self.current_page() == "chat":
            self.chat_view.show_disconnected_banner(reason)
        else:
            self.show_connect()
            self.connect_view.set_error(reason)

    # ---------------------------------------------------------------- auth
    def _login(self, username: str, password: str) -> None:
        self.auth_view.set_loading(True)
        self.client_ctrl.login(username, password)

    def _register(self, username: str, password: str) -> None:
        self._register_user = username
        self.auth_view.set_loading(True)
        self.client_ctrl.register(username, password)

    def _on_auth_succeeded(self, username: str) -> None:
        self._last_username = username
        self.auth_view.set_loading(False)
        self.auth_view.clear_fields()
        self.client_ctrl.set_download_directory_for_user(username, self._download_root)
        host, port = self._endpoint[:2] if self._endpoint else ("?", 0)
        self.chat_view.clear_messages()
        self.chat_view.set_connection_info(host, port, username)
        self.chat_view.set_directory(self.client_ctrl.get_directory())
        self.chat_view.hide_disconnected_banner()
        self.show_chat()

    def _on_auth_failed(self, message: str) -> None:
        self.auth_view.set_loading(False)
        self.auth_view.set_error(message)

    def _on_register_finished(self, ok: bool, message: str) -> None:
        self.auth_view.set_loading(False)
        if ok:
            self.auth_view.show_login_tab(self._register_user)
            self.auth_view.set_info("Đăng ký thành công! Hãy đăng nhập để bắt đầu trò chuyện.")
        else:
            self.auth_view.set_error(message)

    def _cancel_auth(self) -> None:
        self.client_ctrl.disconnect()
        self.show_connect()

    def _disconnect_to_connect_page(self) -> None:
        self.client_ctrl.disconnect()
        self._last_username = ""
        self.chat_view.clear_messages()
        self.chat_view.hide_disconnected_banner()
        self._conn_label.setText("Chưa kết nối máy chủ")
        self.show_connect()

    def _logout(self) -> None:
        if (
            QMessageBox.question(self, "Đăng xuất", "Đăng xuất khỏi tài khoản hiện tại?")
            != QMessageBox.StandardButton.Yes
        ):
            return
        self._disconnect_to_connect_page()

    def _on_chat_sent(self, to, text: str) -> None:
        self.chat_view.add_message({"from": self.client_ctrl.username, "to": to, "text": text})

    # ----------------------------------------------------------- transfers
    def _on_transfer_offer(self, offer: dict) -> None:
        self.transfer_manager.add_incoming_offer(
            str(offer["transfer_id"]),
            str(offer["filename"]),
            str(offer.get("from", "")),
        )
        self.chat_view.add_file_message(
            str(offer["transfer_id"]),
            str(offer["filename"]),
            int(offer.get("size", 0)),
            str(offer.get("from", "")),
            is_own=False,
        )

    def _on_transfer_started(self, info: dict) -> None:
        tid, name = info["transfer_id"], info["filename"]
        if info["direction"] == "send":
            self.transfer_manager.add_outgoing(tid, name, info["peer"])
            self.chat_view.add_file_message(
                tid,
                name,
                int(info.get("size", 0)),
                info["peer"],
                is_own=True,
                recipient=info["peer"],
            )
        else:
            self.transfer_manager.add_incoming(tid, name, info.get("peer", ""))

    def _on_transfer_done(self, tid: str, ok: bool, detail: dict) -> None:
        self.transfer_manager.set_transfer_done(tid, ok, detail)
        if ok:
            self.chat_view.mark_file_done(tid)
        if ok and detail.get("path"):
            msg = f"Đã nhận tệp hoàn tất (SHA-256 khớp): {detail.get('filename')}"
        elif ok:
            msg = "Đã gửi tệp hoàn tất (người nhận đã xác minh SHA-256)!"
        else:
            msg = "Truyền tệp thất bại: " + describe_transfer_error(
                detail.get("code") or detail.get("message")
            )
        self.statusBar().showMessage(msg, 8000)

    def _on_transfer_error(self, message: str) -> None:
        self.chat_view.show_error(message)
        self.statusBar().showMessage(message, 8000)

    def _confirm_cancel(self, tid: str) -> None:
        if (
            QMessageBox.question(self, "Hủy truyền tệp", "Bạn có muốn dừng truyền tệp này?")
            == QMessageBox.StandardButton.Yes
        ):
            self.client_ctrl.cancel_transfer(tid)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.transfer_manager.active_count() and (
            QMessageBox.question(
                self, "Thoát LumiChat", "Đang có tệp đang truyền dở. Bạn vẫn muốn thoát?"
            )
            != QMessageBox.StandardButton.Yes
        ):
            event.ignore()
            return
        self.client_ctrl.shutdown_blocking()
        event.accept()
