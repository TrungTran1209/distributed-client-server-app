"""Interactive command-line user interface for chat, presence, and file transfer."""

from __future__ import annotations

import getpass
from pathlib import Path
import shlex
import threading
from typing import TextIO

from collab.common.errors import ProtocolError, TransferError
from collab.transfer import FileReceiver, FileSender, TransferManifest, TransferProgress
from .connection import ClientConnection, ClientConnectionError


class CommandLine:
    def __init__(
        self,
        connection: ClientConnection,
        *,
        output: TextIO,
        input_fn=input,
        download_dir: str | Path = "downloads",
        auto_accept: bool = False,
    ) -> None:
        self.connection, self.output, self.input_fn = connection, output, input_fn
        self._print_lock = threading.RLock()
        self.running = True
        self.heartbeat = None
        self.users: list[dict] = []
        self.file_sender = FileSender(
            connection.request,
            on_progress=self._on_progress,
            on_complete=self._on_send_complete,
        )
        self.file_receiver = FileReceiver(
            connection.request,
            download_dir=download_dir,
            auto_accept=auto_accept,
            on_offer=self._on_file_offer,
            on_progress=self._on_progress,
            on_complete=self._on_receive_complete,
        )

    def show_event(self, message: dict) -> None:
        if self.file_sender.handle_event(message) or self.file_receiver.handle_event(message):
            return
        kind = message.get("type")
        with self._print_lock:
            if kind == "user_list":
                users = message.get("users", [])
                self.users = list(users)
                names = ", ".join(f"{u['username']} ({u['host']}:{u['port']})" for u in users)
                print(f"[online] {names or 'không có ai'}", file=self.output, flush=True)
            elif kind in {"presence_online", "presence_offline"}:
                username = message.get("username")
                if kind == "presence_online" and not any(u.get("username") == username for u in self.users):
                    self.users = [*self.users, {"username": username, "host": "?", "port": "?"}]
                elif kind == "presence_offline":
                    self.users = [u for u in self.users if u.get("username") != username]
                verb = "đã trực tuyến" if kind.endswith("online") else "đã ngoại tuyến"
                print(f"[{username}] {verb}", file=self.output, flush=True)
            elif kind == "chat_message":
                recipient = "broadcast" if message.get("to") is None else "tin nhắn riêng"
                print(
                    f"\n[{recipient}] {message.get('from')}: {message.get('text')}",
                    file=self.output,
                    flush=True,
                )
            elif kind == "connection_lost":
                self.file_sender.abort_all("connection_lost")
                self.file_receiver.abort_all("connection_lost")
                print(
                    f"\n[Mất kết nối] {message.get('reason', 'Server đã đóng kết nối.')}",
                    file=self.output,
                    flush=True,
                )
                self.running = False

    def run(self) -> None:
        print("Đã kết nối TLS. Gõ /help để xem lệnh.", file=self.output)
        while self.running and self.connection.connected:
            try:
                line = self.input_fn("collab> ")
            except (EOFError, KeyboardInterrupt):
                print(file=self.output)
                break
            try:
                self.execute(line)
            except (ClientConnectionError, TimeoutError, OSError) as exc:
                print(f"Lỗi kết nối: {exc}", file=self.output, flush=True)
                if not self.connection.connected:
                    break
            except (ValueError, TransferError, ProtocolError) as exc:
                print(f"Lỗi lệnh: {exc}", file=self.output, flush=True)
        self.file_sender.abort_all("client_closed")
        self.file_receiver.abort_all("client_closed")
        self.connection.close()

    def execute(self, line: str) -> None:
        parts = shlex.split(line)
        if not parts:
            return
        command, args = parts[0].lower(), parts[1:]
        if command in {"/help", "help"}:
            print(
                "/register USER  /login USER  /users  /all TEXT  /msg USER TEXT  "
                "/file PATH USER  /accept [ID]  /reject [ID]  /cancel [ID]  /quit",
                file=self.output,
            )
        elif command == "/register":
            username = self._one_arg(command, args)
            password = getpass.getpass("Mật khẩu (tối thiểu 8 ký tự): ")
            result = self.connection.request("register", username=username, password=password)
            msg = "Đăng ký thành công." if result.get("ok") else f"Đăng ký thất bại: {result.get('code')}"
            self._println(msg)
        elif command == "/login":
            username = self._one_arg(command, args)
            password = getpass.getpass("Mật khẩu: ")
            result = self.connection.request("login", username=username, password=password)
            msg = (
                f"Đăng nhập thành công: {result.get('username')}"
                if result.get("ok")
                else f"Đăng nhập thất bại: {result.get('code')}"
            )
            self._println(msg)
        elif command == "/users":
            self._no_args(command, args)
            if not self.users:
                self._println("Chưa có danh sách; hãy đăng nhập để nhận danh sách user online.")
            else:
                self._println(", ".join(u["username"] for u in self.users))
        elif command == "/all":
            text = self._text_arg(command, args)
            result = self.connection.request("chat_send", to=None, text=text)
            self._chat_result(result)
        elif command == "/msg":
            if len(args) < 2:
                raise ValueError("dùng /msg USER NỘI_DUNG")
            result = self.connection.request("chat_send", to=args[0], text=" ".join(args[1:]))
            self._chat_result(result)
        elif command == "/file":
            if len(args) != 2:
                raise ValueError("dùng /file ĐƯỜNG_DẪN USER")
            manifest = self.file_sender.start_send(args[0], args[1])
            self._println(
                f"[file] Đã gửi lời mời '{manifest.filename}' ({manifest.size} bytes, "
                f"id: {manifest.transfer_id[:8]}) tới {args[1]} — đang chờ phản hồi..."
            )
        elif command == "/accept":
            prefix = self._optional_id(command, args)
            manifest = self.file_receiver.accept(prefix)
            self._println(
                f"[file] Đã chấp nhận '{manifest.filename}' (id: {manifest.transfer_id[:8]}). Đang nhận tệp..."
            )
        elif command == "/reject":
            prefix = self._optional_id(command, args)
            manifest = self.file_receiver.reject(prefix)
            self._println(f"[file] Đã từ chối '{manifest.filename}' (id: {manifest.transfer_id[:8]}).")
        elif command == "/cancel":
            prefix = self._optional_id(command, args)
            tid = self._cancel_any(prefix)
            self._println(f"[file] Đã hủy phiên truyền {tid[:8]}.")
        elif command in {"/quit", "/exit"}:
            self.running = False
        else:
            raise ValueError(f"không biết {command}; gõ /help")

    def _cancel_any(self, prefix: str | None) -> str:
        try:
            return self.file_sender.cancel(prefix)
        except TransferError:
            return self.file_receiver.cancel(prefix)

    def _on_file_offer(self, manifest: TransferManifest, sender: str) -> None:
        short_id = manifest.transfer_id[:8]
        if self.file_receiver.auto_accept:
            self._println(
                f"\n[file] {sender} gửi '{manifest.filename}' ({manifest.size} bytes, id: {short_id}) — tự động nhận..."
            )
        else:
            self._println(
                f"\n[file] {sender} muốn gửi '{manifest.filename}' ({manifest.size} bytes, "
                f"{manifest.total_chunks} chunks, id: {short_id}). "
                f"Gõ /accept {short_id} hoặc /reject {short_id}."
            )

    def _on_progress(self, progress: TransferProgress) -> None:
        action = "Đang gửi" if progress.direction == "send" else "Đang nhận"
        self._println(
            f"[file {progress.transfer_id[:8]}] {action} '{progress.filename}': "
            f"{progress.percent:.1f}% ({progress.bytes_done}/{progress.total_bytes} bytes)"
        )

    def _on_send_complete(self, transfer_id: str, ok: bool, detail: dict) -> None:
        short_id = transfer_id[:8]
        if ok:
            self._println(f"\n[file {short_id}] Gửi tệp hoàn tất và đã xác minh SHA-256 thành công.")
        else:
            self._println(f"\n[file {short_id}] Gửi tệp không thành công: {detail.get('code', 'failed')}")

    def _on_receive_complete(self, transfer_id: str, ok: bool, detail: dict) -> None:
        short_id = transfer_id[:8]
        if ok:
            self._println(
                f"\n[file {short_id}] Đã nhận thành công '{detail.get('filename')}' -> {detail.get('path')} "
                f"(SHA-256 khớp)."
            )
        else:
            self._println(f"\n[file {short_id}] Nhận tệp thất bại (đã xóa tệp tạm): {detail.get('code', 'failed')}")

    def _println(self, text: str) -> None:
        with self._print_lock:
            print(text, file=self.output, flush=True)

    @staticmethod
    def _one_arg(command: str, args: list[str]) -> str:
        if len(args) != 1:
            raise ValueError(f"dùng {command} USER")
        return args[0]

    @staticmethod
    def _optional_id(command: str, args: list[str]) -> str | None:
        if len(args) > 1:
            raise ValueError(f"dùng {command} [ID]")
        return args[0] if args else None

    @staticmethod
    def _no_args(command: str, args: list[str]) -> None:
        if args:
            raise ValueError(f"{command} không nhận tham số")

    @staticmethod
    def _text_arg(command: str, args: list[str]) -> str:
        if not args:
            raise ValueError(f"dùng {command} NỘI_DUNG")
        return " ".join(args)

    def _chat_result(self, result: dict) -> None:
        msg = "Server đã nhận tin nhắn." if result.get("ok") else f"Không gửi được: {result.get('code')}"
        self._println(msg)
