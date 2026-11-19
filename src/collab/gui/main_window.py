"""Main window: page navigation and wiring between controllers and views."""
from __future__ import annotations

import os
import threading

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
from .controllers.server_controller import ServerController
from .views.auth_view import AuthView
from .views.chat_view import ChatView
from .views.connect_view import ConnectView
from .views.home_view import HomeView
from .views.host_view import HostView
from .widgets.formatting import describe_transfer_error
from .widgets.transfer_manager import TransferManagerWidget

_PAGES = ("home", "host", "connect", "auth", "chat")


class MainWindow(QMainWindow):
    def __init__(self, server_ctrl: ServerController, client_ctrl: ClientController) -> None:
        super().__init__()
        self.server_ctrl, self.client_ctrl = server_ctrl, client_ctrl
        self.setWindowTitle("Collab — Trò chuyện & gửi tệp")
        self.setMinimumSize(1024, 680)
        self._endpoint: tuple[str, int, str, str] | None = None  # host, port, ca, download dir
        self._offers: dict[str, dict] = {}
        self._offer_senders: dict[str, str] = {}
        self._register_user = ""

        self.home_view, self.host_view = HomeView(), HostView()
        self.connect_view, self.auth_view, self.chat_view = ConnectView(), AuthView(), ChatView()
        self._stack = QStackedWidget()
        for view in (self.home_view, self.host_view, self.connect_view, self.auth_view, self.chat_view):
            self._stack.addWidget(view)
        self.setCentralWidget(self._stack)

        self.transfer_manager = TransferManagerWidget()
        self._dock = QDockWidget("Lịch sử tệp", self)
        self._dock.setWidget(self.transfer_manager)
        self._dock.setMinimumWidth(340)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._dock)
        self._dock.hide()

        self._conn_label = QLabel("Chưa kết nối")
        self.statusBar().addPermanentWidget(self._conn_label)
        self._wire_views()
        self._wire_server()
        self._wire_client()
        self.show_home()

    # ---------------------------------------------------------- navigation
    def _show(self, name: str) -> None:
        self._stack.setCurrentIndex(_PAGES.index(name))

    def current_page(self) -> str:
        return _PAGES[self._stack.currentIndex()]

    def show_home(self) -> None:
        self._show("home")

    def show_host(self) -> None:
        self._show("host")

    def show_connect(self) -> None:
        self._show("connect")

    def show_auth(self) -> None:
        self._show("auth")

    def show_chat(self) -> None:
        self._show("chat")

    def pending_offer_count(self) -> int:
        return len(self._offers)

    # -------------------------------------------------------------- wiring
    def _wire_views(self) -> None:
        self.home_view.host_requested.connect(self.show_host)
        self.home_view.join_requested.connect(self.show_connect)
        self.host_view.back_requested.connect(self.show_home)
        self.host_view.start_requested.connect(self._start_server)
        self.host_view.stop_requested.connect(self._stop_server)
        self.host_view.connect_to_local_requested.connect(self._connect_local)
        self.connect_view.back_requested.connect(self.show_home)
        self.connect_view.connect_requested.connect(self._begin_connect)
        self.connect_view.discover_requested.connect(self._discover)
        self.auth_view.back_requested.connect(self._cancel_auth)
        self.auth_view.login_requested.connect(self._login)
        self.auth_view.register_requested.connect(self._register)
        self.chat_view.send_requested.connect(lambda text, to: self.client_ctrl.send_chat(to, text))
        self.chat_view.file_send_requested.connect(self.client_ctrl.send_file)
        self.chat_view.logout_requested.connect(self._logout)
        self.chat_view.transfers_panel_requested.connect(self._toggle_dock)
        self.chat_view.reconnect_requested.connect(self._reconnect)
        self.transfer_manager.cancel_requested.connect(self._confirm_cancel)
        self.transfer_manager.download_requested.connect(self.client_ctrl.accept_file)
        self.chat_view.file_download_requested.connect(self.client_ctrl.accept_file)
        self.chat_view._users.recipient_changed.connect(self.transfer_manager.set_conversation)

    def _wire_server(self) -> None:
        s = self.server_ctrl
        s.server_started.connect(self._on_server_started)
        s.server_stopped.connect(self._on_server_stopped)
        s.server_error.connect(self._on_server_error)
        s.log_message.connect(self.host_view.append_log)
        s.client_count_changed.connect(self.host_view.set_client_count)

    def _wire_client(self) -> None:
        c = self.client_ctrl
        c.connected.connect(self._on_connected)
        c.connection_lost.connect(self._on_connection_lost)
        c.discovery_finished.connect(self._on_discovery_finished)
        c.discovery_failed.connect(self._on_discovery_failed)
        c.auth_succeeded.connect(self._on_auth_succeeded)
        c.auth_failed.connect(self._on_auth_failed)
        c.register_finished.connect(self._on_register_finished)
        c.users_updated.connect(self.chat_view.set_users)
        c.presence_changed.connect(lambda *_: self.chat_view.set_users(self.client_ctrl.get_users()))
        c.message_received.connect(self.chat_view.add_message)
        c.chat_sent.connect(self._on_chat_sent)
        c.chat_failed.connect(self.chat_view.show_error)
        c.transfer_offer.connect(self._on_offer)
        c.transfer_started.connect(self._on_transfer_started)
        c.transfer_progress.connect(lambda p: self.transfer_manager.update_progress(p.transfer_id, p))
        c.transfer_done.connect(self._on_transfer_done)
        c.transfer_error.connect(self._on_transfer_error)

    # --------------------------------------------------------------- server
    def _start_server(self, config: dict) -> None:
        self.host_view.append_log("Đang khởi chạy server…")
        self.host_view._btn_start.setEnabled(False)
        self.server_ctrl.start_server(config)

    def _stop_server(self) -> None:
        clients = self.server_ctrl.client_count()
        if (clients or self.transfer_manager.active_count()) and QMessageBox.question(
            self, "Dừng server",
            f"Đang có {clients} người kết nối. Dừng server sẽ ngắt kết nối họ. Tiếp tục?",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.host_view._btn_stop.setEnabled(False)
        # stop_server joins threads: keep that off the UI thread
        threading.Thread(target=self.server_ctrl.stop_server, name="collab-server-stop", daemon=True).start()

    def _on_server_started(self) -> None:
        self.host_view.set_running(True)
        self.host_view.clear_error()
        self.home_view.set_status("Server đang hoạt động", "success")

    def _on_server_stopped(self) -> None:
        self.host_view.set_running(False)
        self.home_view.set_status("Server đã dừng", "muted")
        self.host_view.append_log("Server đã dừng.")

    def _on_server_error(self, message: str) -> None:
        self.host_view.set_running(False)
        self.host_view.set_error(message)
        self.host_view.append_log(f"Lỗi: {message}")
        self.home_view.set_status("Server gặp lỗi", "error")

    def _connect_local(self, host: str, port: int) -> None:
        cfg = self.host_view.get_config()
        self._begin_connect(host, port, cfg["cert"], "downloads")
        self.show_connect()

    # --------------------------------------------------------------- client
    def _begin_connect(self, host: str, port: int, ca: str, download_dir: str) -> None:
        if ca and not os.path.isfile(ca):
            self.connect_view.set_error(f"Không tìm thấy file chứng chỉ CA: {ca}")
            return
        try:
            ctx = create_client_context(ca or None)
        except Exception as exc:  # noqa: BLE001 - bad CA file etc.
            self.connect_view.set_error(f"Không đọc được chứng chỉ CA: {exc}")
            return
        self._endpoint = (host, port, ca, download_dir)
        self.connect_view.clear_error()
        self.connect_view.set_connecting(True)
        self.home_view.set_status("Đang kết nối…", "info")
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
        self.client_ctrl.discover(udp_port, broadcast, "255.255.255.255" if broadcast else "127.0.0.1")

    def _on_discovery_finished(self, info) -> None:
        self.connect_view.set_discovering(False)
        if info is None:
            self.connect_view.set_error("Không tìm thấy server nào. Kiểm tra server đang chạy, cổng UDP và mạng LAN.")
        else:
            self.connect_view.add_discovered_server(info)

    def _on_discovery_failed(self, message: str) -> None:
        self.connect_view.set_discovering(False)
        self.connect_view.set_error(f"Dò tìm thất bại: {message}")

    def _on_connected(self, _welcome: dict) -> None:
        self.connect_view.set_connecting(False)
        self.chat_view._btn_reconnect.setEnabled(True)
        host, port = self._endpoint[:2] if self._endpoint else ("?", 0)
        self.home_view.set_status(f"Đã kết nối {host}:{port}", "success")
        self._conn_label.setText(f"Đã kết nối {host}:{port} (TLS)")
        self.auth_view.clear_error()
        self.auth_view.set_loading(False)
        self.show_auth()

    def _on_connection_lost(self, reason: str) -> None:
        self.connect_view.set_connecting(False)
        self.chat_view._btn_reconnect.setEnabled(True)
        self.home_view.set_status("Mất kết nối", "error")
        self._conn_label.setText("Mất kết nối")
        page = self.current_page()
        if page == "chat":
            self.chat_view.show_disconnected_banner(reason)
        else:
            if page == "auth":
                self.show_connect()
            self.connect_view.set_error(reason)

    # ----------------------------------------------------------------- auth
    def _login(self, username: str, password: str) -> None:
        self.auth_view.set_loading(True)
        self.client_ctrl.login(username, password)

    def _register(self, username: str, password: str) -> None:
        self._register_user = username
        self.auth_view.set_loading(True)
        self.client_ctrl.register(username, password)

    def _on_auth_succeeded(self, username: str) -> None:
        self.auth_view.set_loading(False)
        self.auth_view.clear_fields()
        host, port = self._endpoint[:2] if self._endpoint else ("?", 0)
        self.chat_view.set_connection_info(host, port, username)
        self.chat_view.set_users(self.client_ctrl.get_users())
        self.chat_view.hide_disconnected_banner()
        self.show_chat()

    def _on_auth_failed(self, message: str) -> None:
        self.auth_view.set_loading(False)
        self.auth_view.set_error(message)

    def _on_register_finished(self, ok: bool, message: str) -> None:
        self.auth_view.set_loading(False)
        if ok:
            self.auth_view.show_login_tab(self._register_user)
            self.auth_view.set_info("Đăng ký thành công. Hãy đăng nhập.")
        else:
            self.auth_view.set_error(message)

    def _cancel_auth(self) -> None:
        self.client_ctrl.disconnect()
        self.show_connect()

    def _logout(self) -> None:
        if QMessageBox.question(self, "Đăng xuất", "Đăng xuất và ngắt kết nối?") != QMessageBox.StandardButton.Yes:
            return
        self.client_ctrl.disconnect()
        self.chat_view.clear_messages()
        self.home_view.set_status("Chưa kết nối", "muted")
        self._conn_label.setText("Chưa kết nối")
        self.show_connect()

    def _on_chat_sent(self, to, text: str) -> None:
        self.chat_view.add_message({"from": self.client_ctrl.username, "to": to, "text": text})

    # ------------------------------------------------------------ transfers
    def _toggle_dock(self) -> None:
        self._dock.setVisible(not self._dock.isVisible())

    def _on_offer(self, offer: dict) -> None:
        tid = str(offer.get("transfer_id"))
        self._offers[tid] = dict(offer)
        self._offer_senders[tid] = str(offer.get("from", ""))
        self.transfer_manager.add_incoming_offer(
            tid,
            str(offer.get("filename", "")),
            str(offer.get("from", "")),
        )
        self.chat_view.add_file_message(
            tid,
            str(offer.get("filename", "")),
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
            self.transfer_manager.add_incoming(tid, name, info["peer"] or self._offer_senders.get(tid, ""))

    def _on_transfer_done(self, tid: str, ok: bool, detail: dict) -> None:
        self._offers.pop(tid, None)
        self.transfer_manager.set_transfer_done(tid, ok, detail)
        if ok:
            self.chat_view.mark_file_done(tid)
        text = "Truyền tệp hoàn tất" if ok else "Truyền tệp thất bại: " + describe_transfer_error(
            detail.get("code") or detail.get("message"))
        self.statusBar().showMessage(text, 8000)

    def _on_transfer_error(self, message: str) -> None:
        self.chat_view.show_error(message)
        self.statusBar().showMessage(message, 8000)

    def _confirm_cancel(self, tid: str) -> None:
        if QMessageBox.question(self, "Hủy truyền tệp", "Bạn có chắc muốn hủy truyền tệp này?") == QMessageBox.StandardButton.Yes:
            self.client_ctrl.cancel_transfer(tid)

    # ---------------------------------------------------------------- close
    def closeEvent(self, event) -> None:  # noqa: N802
        busy = self.transfer_manager.active_count() or (
            self.server_ctrl.is_running() and self.server_ctrl.client_count())
        if busy and QMessageBox.question(
            self, "Thoát", "Đang có truyền tệp hoặc người dùng kết nối. Thoát ứng dụng?"
        ) != QMessageBox.StandardButton.Yes:
            event.ignore()
            return
        self.client_ctrl.shutdown_blocking()
        self.server_ctrl.stop_server()
        event.accept()
