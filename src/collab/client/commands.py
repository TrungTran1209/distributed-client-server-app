"""Interactive, deliberately small command-line user interface."""

from __future__ import annotations

import getpass
import shlex
import threading
from typing import TextIO

from .connection import ClientConnection, ClientConnectionError


class CommandLine:
    def __init__(self, connection: ClientConnection, *, output: TextIO, input_fn=input) -> None:
        self.connection, self.output, self.input_fn = connection, output, input_fn
        self._print_lock = threading.Lock()
        self.running = True
        self.heartbeat = None
        self.users: list[dict] = []

    def show_event(self, message: dict) -> None:
        kind = message.get("type")
        with self._print_lock:
            if kind == "user_list":
                users = message.get("users", [])
                self.users = users
                names = ", ".join(f"{u['username']} ({u['host']}:{u['port']})" for u in users)
                print(f"[online] {names or 'không có ai'}", file=self.output, flush=True)
            elif kind in {"presence_online", "presence_offline"}:
                username = message.get("username")
                if kind == "presence_online" and not any(u.get("username") == username for u in self.users):
                    self.users.append({"username": username, "host": "?", "port": "?"})
                elif kind == "presence_offline":
                    self.users = [u for u in self.users if u.get("username") != username]
                verb = "đã trực tuyến" if kind.endswith("online") else "đã ngoại tuyến"
                print(f"[{username}] {verb}", file=self.output, flush=True)
            elif kind == "chat_message":
                recipient = "broadcast" if message.get("to") is None else "tin nhắn riêng"
                print(f"\n[{recipient}] {message.get('from')}: {message.get('text')}", file=self.output, flush=True)
            elif kind == "connection_lost":
                print(f"\n[Mất kết nối] {message.get('reason', 'Server đã đóng kết nối.')}", file=self.output, flush=True)
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
            except ValueError as exc:
                print(f"Lệnh không hợp lệ: {exc}", file=self.output, flush=True)
        self.connection.close()

    def execute(self, line: str) -> None:
        parts = shlex.split(line)
        if not parts:
            return
        command, args = parts[0].lower(), parts[1:]
        if command in {"/help", "help"}:
            print("/register USER  /login USER  /users  /all TEXT  /msg USER TEXT  /file PATH [USER]  /quit", file=self.output)
        elif command == "/register":
            username = self._one_arg(command, args)
            password = getpass.getpass("Mật khẩu (tối thiểu 8 ký tự): ")
            result = self.connection.request("register", username=username, password=password)
            print("Đăng ký thành công." if result.get("ok") else f"Đăng ký thất bại: {result.get('code')}", file=self.output)
        elif command == "/login":
            username = self._one_arg(command, args)
            password = getpass.getpass("Mật khẩu: ")
            result = self.connection.request("login", username=username, password=password)
            print(f"Đăng nhập thành công: {result.get('username')}" if result.get("ok") else f"Đăng nhập thất bại: {result.get('code')}", file=self.output)
        elif command == "/users":
            self._no_args(command, args)
            if not self.users:
                print("Chưa có danh sách; hãy đăng nhập để nhận danh sách user online.", file=self.output)
            else:
                print(", ".join(u["username"] for u in self.users), file=self.output)
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
            if not 1 <= len(args) <= 2:
                raise ValueError("dùng /file PATH [USER]")
            print("Truyền tệp chưa khả dụng: server hiện chưa tích hợp transfer handler.", file=self.output)
        elif command in {"/quit", "/exit"}:
            self.running = False
        else:
            raise ValueError(f"không biết {command}; gõ /help")

    @staticmethod
    def _one_arg(command: str, args: list[str]) -> str:
        if len(args) != 1:
            raise ValueError(f"dùng {command} USER")
        return args[0]

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
        print("Server đã nhận tin nhắn." if result.get("ok") else f"Không gửi được: {result.get('code')}", file=self.output)
