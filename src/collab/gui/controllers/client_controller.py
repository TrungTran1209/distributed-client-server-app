"""ClientController — manages a persistent TLS connection, online/offline directory,
SQLite chat history sync, and automatic (zero-prompt) SHA-256 chunked file reception.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QThreadPool, QTimer, Signal

from collab.client.connection import ClientConnectionError
from collab.common.errors import TransferError
from collab.common.protocol import normalize_username
from collab.transfer import FileReceiver, FileSender

from ..workers.async_workers import (
    AuthWorker,
    CallWorker,
    ChatWorker,
    ConnectWorker,
    DiscoveryWorker,
    FileSendWorker,
)

log = logging.getLogger(__name__)


class ClientController(QObject):
    connected = Signal(dict)
    connection_lost = Signal(str)
    users_updated = Signal(list)
    directory_updated = Signal(list)
    history_loaded = Signal(list)
    message_received = Signal(dict)
    presence_changed = Signal(str, bool)
    auth_succeeded = Signal(str)
    auth_failed = Signal(str)
    register_finished = Signal(bool, str)
    chat_failed = Signal(str)
    chat_sent = Signal(object, str)
    chat_queued_offline = Signal(str)
    transfer_offer = Signal(dict)
    transfer_started = Signal(dict)
    transfer_progress = Signal(object)
    transfer_done = Signal(str, bool, dict)
    transfer_error = Signal(str)
    discovery_finished = Signal(object)
    discovery_failed = Signal(str)

    def __init__(self, parent: QObject | None = None, *, auto_accept: bool = True) -> None:
        super().__init__(parent)
        self._conn: Any = None
        self._heartbeat: Any = None
        self._users: list[dict] = []
        self._directory: list[dict] = []
        self.username: str | None = None
        self.auto_accept = auto_accept
        self._pool = QThreadPool.globalInstance()
        self._workers: set = set()
        self.file_sender = FileSender(
            self._request,
            on_progress=lambda p: self.transfer_progress.emit(p),
            on_complete=lambda tid, ok, d: self.transfer_done.emit(tid, ok, dict(d)),
        )
        self.file_receiver = FileReceiver(
            self._request,
            auto_accept=auto_accept,
            on_offer=self._on_offer,
            on_progress=lambda p: self.transfer_progress.emit(p),
            on_complete=lambda tid, ok, d: self.transfer_done.emit(tid, ok, dict(d)),
        )
        self._dir_timer = QTimer(self)
        self._dir_timer.setInterval(4000)
        self._dir_timer.timeout.connect(self.refresh_directory)

    def _start(self, worker) -> None:
        worker.setAutoDelete(False)
        self._workers.add(worker)
        worker.signals.finished.connect(lambda w=worker: self._workers.discard(w))
        self._pool.start(worker)

    # ------------------------------------------------------------- queries
    def is_connected(self) -> bool:
        return bool(self._conn is not None and self._conn.connected)

    def get_users(self) -> list[dict]:
        return list(self._users)

    def get_directory(self) -> list[dict]:
        return list(self._directory)

    def set_download_directory_for_user(self, username: str, root: str | Path) -> Path:
        """Store received files below ``root/<username>`` after authentication."""
        user_dir = Path(root).expanduser() / normalize_username(username)
        user_dir.mkdir(parents=True, exist_ok=True)
        self.file_receiver.download_dir = user_dir
        return user_dir

    # --------------------------------------------------------- connection
    def _request(self, kind: str, **fields: Any) -> dict[str, Any]:
        conn = self._conn
        if conn is None:
            raise ClientConnectionError("Chưa kết nối tới server")
        return conn.request(kind, **fields)

    def connect_to_server(
        self,
        host: str,
        port: int,
        tls_context,
        download_dir: str,
        udp_port: int | None = 37020,
    ) -> None:
        self.file_receiver.download_dir = Path(download_dir)
        worker = ConnectWorker(host, port, tls_context, download_dir, self._on_server_event)
        worker.signals.result.connect(lambda r: self._on_connected(r, host, udp_port))
        worker.signals.error.connect(self.connection_lost.emit)
        self._start(worker)

    def _on_connected(self, result: tuple, host: str, udp_port: int | None) -> None:
        self._conn, welcome = result
        if udp_port:
            from collab.client.discovery import UDPHeartbeat

            interval = max(5, int(welcome.get("heartbeat_interval_sec", 30)))
            self._heartbeat = UDPHeartbeat(host, udp_port, interval=interval)
            self._heartbeat.start()
        self.connected.emit(dict(welcome))

    def disconnect(self) -> None:
        self._dir_timer.stop()
        conn, self._conn = self._conn, None
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        self.file_sender.abort_all("disconnected")
        self.file_receiver.abort_all("disconnected")
        self._users = []
        self._directory = []
        self.username = None
        if conn is not None:
            self._start(CallWorker(conn.close))

    def shutdown_blocking(self) -> None:
        self._dir_timer.stop()
        conn, self._conn = self._conn, None
        if self._heartbeat is not None:
            self._heartbeat.stop()
            self._heartbeat = None
        self.file_sender.abort_all("disconnected")
        self.file_receiver.abort_all("disconnected")
        if conn is not None:
            conn.close()

    # ------------------------------------------------------------- events
    def _on_server_event(self, event: dict) -> None:
        if self.file_sender.handle_event(event) or self.file_receiver.handle_event(event):
            return
        kind = event.get("type")
        if kind == "connection_lost":
            self.file_sender.abort_all("connection_lost")
            self.file_receiver.abort_all("connection_lost")
            self._conn = None
            self._users = []
            self.connection_lost.emit(str(event.get("reason", "Server đã đóng kết nối.")))
        elif kind == "user_list":
            raw = event.get("users")
            self._users = [u for u in raw if isinstance(u, dict)] if isinstance(raw, list) else []
            raw_dir = event.get("directory")
            if isinstance(raw_dir, list):
                self._directory = [dict(d) for d in raw_dir if isinstance(d, dict)]
            else:
                self._merge_online_into_directory(self._users)
            self.users_updated.emit(list(self._users))
            self.directory_updated.emit(list(self._directory))
        elif kind in {"presence_online", "presence_offline"}:
            name = str(event.get("username", ""))
            online = kind == "presence_online"
            if online and not any(u.get("username") == name for u in self._users):
                self._users = [*self._users, {"username": name, "host": None, "port": None}]
            elif not online:
                self._users = [u for u in self._users if u.get("username") != name]
            self._update_directory_presence(name, online)
            self.presence_changed.emit(name, online)
            self.directory_updated.emit(list(self._directory))
        elif kind == "chat_message":
            self.message_received.emit(dict(event))

    def _merge_online_into_directory(self, online_users: list[dict]) -> None:
        online_map = {str(u.get("username")): u for u in online_users if u.get("username")}
        by_name = {str(d.get("username")): dict(d) for d in self._directory if d.get("username")}
        for uname in list(by_name.keys()):
            if uname in online_map:
                by_name[uname]["online"] = True
                by_name[uname]["host"] = online_map[uname].get("host")
                by_name[uname]["port"] = online_map[uname].get("port")
            else:
                by_name[uname]["online"] = False
                by_name[uname]["host"] = None
                by_name[uname]["port"] = None
        for uname, u in online_map.items():
            if uname not in by_name:
                by_name[uname] = {
                    "username": uname,
                    "online": True,
                    "host": u.get("host"),
                    "port": u.get("port"),
                }
        self._directory = sorted(by_name.values(), key=lambda item: str(item["username"]))

    def _update_directory_presence(self, username: str, online: bool) -> None:
        if not username:
            return
        updated = False
        next_dir: list[dict] = []
        for entry in self._directory:
            if entry.get("username") == username:
                item = dict(entry)
                item["online"] = online
                if not online:
                    item["host"] = None
                    item["port"] = None
                next_dir.append(item)
                updated = True
            else:
                next_dir.append(dict(entry))
        if not updated:
            next_dir.append({"username": username, "online": online, "host": None, "port": None})
            next_dir.sort(key=lambda item: str(item["username"]))
        self._directory = next_dir

    def _on_offer(self, manifest, sender: str) -> None:
        offer_dict = {
            "transfer_id": manifest.transfer_id,
            "from": sender,
            "filename": manifest.filename,
            "size": manifest.size,
            "sha256": manifest.sha256,
            "chunk_size": manifest.chunk_size,
            "total_chunks": manifest.total_chunks,
        }
        self.transfer_offer.emit(offer_dict)

    # --------------------------------------------------------------- auth
    def login(self, username: str, password: str) -> None:
        self._auth("login", username, password)

    def register(self, username: str, password: str) -> None:
        self._auth("register", username, password)

    def _auth(self, action: str, username: str, password: str) -> None:
        if not self.is_connected():
            self.auth_failed.emit("Chưa kết nối tới server.")
            return
        worker = AuthWorker(self._conn, action, username, password)
        worker.signals.result.connect(lambda r: self._on_auth_result(action, username, r))
        worker.signals.error.connect(self.auth_failed.emit)
        self._start(worker)

    def _on_auth_result(self, action: str, username: str, resp: dict) -> None:
        ok = bool(resp.get("ok"))
        if action == "register":
            self.register_finished.emit(ok, "" if ok else describe_error(resp))
        elif ok:
            self.username = str(resp.get("username", username))
            self.auth_succeeded.emit(self.username)
            self.fetch_history()
            self.refresh_directory()
            self._dir_timer.start()
        else:
            self.auth_failed.emit(describe_error(resp))

    def fetch_history(self, limit: int = 300) -> None:
        if not self.is_connected():
            return
        worker = CallWorker(lambda: self._request("chat_history", limit=limit))
        worker.signals.result.connect(self._on_history_result)
        self._start(worker)

    def _on_history_result(self, resp: dict) -> None:
        if isinstance(resp, dict) and resp.get("ok"):
            msgs = resp.get("messages")
            if isinstance(msgs, list):
                self.history_loaded.emit([dict(m) for m in msgs if isinstance(m, dict)])

    def refresh_directory(self) -> None:
        if not self.is_connected() or not self.username:
            return
        worker = CallWorker(lambda: self._request("user_directory"))
        worker.signals.result.connect(self._on_directory_result)
        self._start(worker)

    def _on_directory_result(self, resp: dict) -> None:
        if isinstance(resp, dict) and resp.get("ok"):
            raw_dir = resp.get("directory")
            if isinstance(raw_dir, list):
                self._directory = [dict(d) for d in raw_dir if isinstance(d, dict)]
                self.directory_updated.emit(list(self._directory))

    # ------------------------------------------------------- chat / files
    def send_chat(self, to: str | None, text: str) -> None:
        if not self.is_connected():
            self.chat_failed.emit("Mất kết nối — không thể gửi tin nhắn.")
            return
        worker = ChatWorker(self._conn, to, text)
        worker.signals.result.connect(lambda r: self._on_chat_result(to, text, r))
        worker.signals.error.connect(self.chat_failed.emit)
        self._start(worker)

    def _on_chat_result(self, to: str | None, text: str, resp: dict) -> None:
        if resp.get("ok"):
            self.chat_sent.emit(to, text)
            if resp.get("queued_offline") and to:
                self.chat_queued_offline.emit(to)
        else:
            self.chat_failed.emit(describe_error(resp))

    def send_file(self, path: str, recipient: str | list[str]) -> None:
        if isinstance(recipient, list):
            for target in recipient:
                self._send_file_to(path, target)
            return
        self._send_file_to(path, recipient)

    def _send_file_to(self, path: str, recipient: str) -> None:
        worker = FileSendWorker(self.file_sender, path, recipient)
        worker.signals.result.connect(
            lambda m: self.transfer_started.emit(
                {
                    "direction": "send",
                    "transfer_id": m.transfer_id,
                    "filename": m.filename,
                    "size": m.size,
                    "total_chunks": m.total_chunks,
                    "peer": recipient,
                }
            )
        )
        worker.signals.error.connect(self.transfer_error.emit)
        self._start(worker)

    def accept_file(self, transfer_id: str) -> None:
        def _accept():
            try:
                return self.file_receiver.accept(transfer_id)
            except TransferError as exc:
                if exc.code == "unknown_transfer" and self.file_receiver.auto_accept:
                    return None
                raise

        worker = CallWorker(_accept)
        worker.signals.result.connect(
            lambda m: None
            if m is None
            else self.transfer_started.emit(
                {
                    "direction": "receive",
                    "transfer_id": m.transfer_id,
                    "filename": m.filename,
                    "size": m.size,
                    "total_chunks": m.total_chunks,
                    "peer": "",
                }
            )
        )
        worker.signals.error.connect(self.transfer_error.emit)
        self._start(worker)

    def reject_file(self, transfer_id: str, reason: str = "rejected_by_user") -> None:
        worker = CallWorker(self.file_receiver.reject, transfer_id, reason)
        worker.signals.error.connect(self.transfer_error.emit)
        self._start(worker)

    def cancel_transfer(self, transfer_id: str) -> None:
        def _cancel() -> None:
            try:
                self.file_sender.cancel(transfer_id)
                return
            except Exception:  # noqa: BLE001
                pass
            self.file_receiver.cancel(transfer_id)

        worker = CallWorker(_cancel)
        worker.signals.error.connect(self.transfer_error.emit)
        self._start(worker)

    def discover(self, udp_port: int, broadcast: bool = False, target_host: str = "127.0.0.1") -> None:
        worker = DiscoveryWorker(udp_port, broadcast, target_host)
        worker.signals.result.connect(self.discovery_finished.emit)
        worker.signals.error.connect(self.discovery_failed.emit)
        self._start(worker)


_ERROR_TEXT = {
    "invalid_credentials": "Sai tên đăng nhập hoặc mật khẩu.",
    "already_online": "Tài khoản này đang đăng nhập ở nơi khác.",
    "rate_limited": "Thao tác quá nhanh / thử sai quá nhiều lần. Vui lòng đợi rồi thử lại.",
    "username_taken": "Tên đăng nhập đã tồn tại.",
    "user_exists": "Tên đăng nhập đã tồn tại.",
    "recipient_unavailable": "Người nhận không tồn tại trong hệ thống.",
    "invalid_message": "Dữ liệu không hợp lệ (kiểm tra tên đăng nhập/mật khẩu 8–128 ký tự).",
    "unauthorized": "Bạn cần đăng nhập trước.",
}


def describe_error(resp: dict) -> str:
    code = str(resp.get("code", ""))
    return _ERROR_TEXT.get(code) or str(resp.get("message") or code or "Yêu cầu bị từ chối.")
