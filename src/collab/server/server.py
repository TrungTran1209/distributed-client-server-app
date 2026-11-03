"""Concurrent TCP/TLS server for authentication, presence and chat."""

from __future__ import annotations

import logging
import socket
import ssl
import threading
import uuid
from typing import Any

from collab.common.errors import ProtocolError
from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import (
    MAX_CHAT_LENGTH, MessageType, decode_message, encode_message, make_message,
)
from .auth import AuthService
from .router import MessageRouter
from .sessions import Session, SessionRegistry

log = logging.getLogger(__name__)


class CollaborationServer:
    def __init__(
        self,
        host: str,
        port: int,
        tls_context: ssl.SSLContext,
        auth: AuthService,
        *,
        max_clients: int = 100,
        idle_timeout: int = 90,
    ) -> None:
        self.host, self.port = host, port
        self.tls_context, self.auth = tls_context, auth
        self.max_clients, self.idle_timeout = max_clients, idle_timeout
        self.sessions = SessionRegistry()
        self.router = MessageRouter(self.sessions, self._send)
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()

    def serve_forever(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.host, self.port))
        listener.listen(64)
        listener.settimeout(1.0)
        self._listener = listener
        log.info("TLS server listening on %s:%d", *listener.getsockname()[:2])
        try:
            while not self._stop.is_set():
                try:
                    raw, address = listener.accept()
                except socket.timeout:
                    self._reap_idle_sessions()
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    log.exception("TCP listener failed")
                    break
                with self._workers_lock:
                    active = sum(worker.is_alive() for worker in self._workers)
                if active >= self.max_clients:
                    raw.close()
                    continue
                worker = threading.Thread(
                    target=self._handle_connection,
                    args=(raw, address),
                    name=f"client-{address[0]}:{address[1]}",
                    daemon=True,
                )
                with self._workers_lock:
                    self._workers.add(worker)
                worker.start()
        finally:
            listener.close()
            self._listener = None

    def shutdown(self) -> None:
        self._stop.set()
        if self._listener is not None:
            try:
                self._listener.close()
            except OSError:
                pass
        for session in self.sessions.snapshot():
            try:
                session.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _handle_connection(self, raw: socket.socket, address: tuple[Any, ...]) -> None:
        tls_sock: ssl.SSLSocket | None = None
        try:
            raw.settimeout(10)
            tls_sock = self.tls_context.wrap_socket(raw, server_side=True)
            # The idle-session reaper closes stale authenticated sockets. A
            # single frame read may therefore block without losing partial data.
            tls_sock.settimeout(self.idle_timeout)
            self._connection_loop(tls_sock, address)
        except (ssl.SSLError, OSError, EOFError, ProtocolError) as exc:
            log.info("Client connection ended (%s)", type(exc).__name__)
        finally:
            sock = tls_sock or raw
            session = self.sessions.remove(sock)
            if session:
                self.router.broadcast_presence(MessageType.PRESENCE_OFFLINE, session.username)
            try:
                sock.close()
            except OSError:
                pass
            current = threading.current_thread()
            with self._workers_lock:
                self._workers.discard(current)

    def _connection_loop(self, sock: ssl.SSLSocket, address: tuple[Any, ...]) -> None:
        greeted = False
        while not self._stop.is_set():
            try:
                request = decode_message(recv_frame(sock))
            except socket.timeout:
                return
            session = self.sessions.get_socket(sock)
            if session:
                self.sessions.touch(sock)
            kind = request["type"]
            request_id = request.get("request_id")
            if not greeted:
                if kind != MessageType.HELLO:
                    self._send_raw(sock, make_message(MessageType.ERROR, request_id=request_id,
                                                      code="invalid_message", message="Send hello first"))
                    return
                greeted = True
                self._send_raw(sock, make_message(
                    MessageType.WELCOME, request_id=request_id, protocol_version=1,
                    server_name="collab", heartbeat_interval_sec=30,
                ))
                continue
            try:
                self._dispatch(sock, address, request, session)
            except ProtocolError as exc:
                self._send_raw(sock, make_message(
                    MessageType.ERROR, request_id=request_id, code="invalid_message", message=str(exc)
                ))

    def _dispatch(self, sock, address, request, session: Session | None) -> None:
        kind = request["type"]
        request_id = request.get("request_id")
        if kind == MessageType.PING:
            self._send_raw(sock, make_message(MessageType.PONG, request_id=request_id))
            return
        if kind == MessageType.REGISTER and session is None:
            try:
                ok, _ = self.auth.register(request.get("username"), request.get("password"))
                response = {"ok": ok}
                if not ok:
                    response["code"] = "username_taken"
            except ProtocolError as exc:
                response = {"ok": False, "code": "invalid_message", "message": str(exc)}
            self._send_raw(sock, make_message(MessageType.REGISTER_RESULT, request_id=request_id, **response))
            return
        if kind == MessageType.LOGIN and session is None:
            try:
                ok, username = self.auth.login(request.get("username"), request.get("password"))
            except ProtocolError:
                ok, username = False, ""
            if not ok:
                self._send_raw(sock, make_message(
                    MessageType.LOGIN_RESULT, request_id=request_id,
                    ok=False, code="invalid_credentials",
                ))
                return
            new_session = Session(username, sock, str(address[0]), int(address[1]), str(uuid.uuid4()))
            if not self.sessions.add(new_session):
                self._send_raw(sock, make_message(
                    MessageType.LOGIN_RESULT, request_id=request_id, ok=False, code="already_online"
                ))
                return
            self._send_raw(sock, make_message(
                MessageType.LOGIN_RESULT, request_id=request_id, ok=True,
                username=username, session_id=new_session.session_id,
            ))
            self._send_raw(sock, make_message(MessageType.USER_LIST, users=self.router.user_list()))
            self.router.broadcast_presence(MessageType.PRESENCE_ONLINE, username, exclude=sock)
            return
        if kind == MessageType.LOGOUT and session is not None:
            self._send_raw(sock, make_message(MessageType.LOGOUT_RESULT, request_id=request_id, ok=True))
            removed = self.sessions.remove(sock)
            if removed:
                self.router.broadcast_presence(MessageType.PRESENCE_OFFLINE, removed.username)
            return
        if session is None:
            self._send_raw(sock, make_message(
                MessageType.ERROR, request_id=request_id, code="unauthorized", message="Login required"
            ))
            return
        if kind == MessageType.CHAT_SEND:
            recipient = request.get("to")
            text = request.get("text")
            if recipient is not None and not isinstance(recipient, str):
                raise ProtocolError("to must be a username or null")
            if not isinstance(text, str) or not text or len(text) > MAX_CHAT_LENGTH:
                raise ProtocolError("text must contain 1-4000 characters")
            ok, message_id, error = self.router.chat(session.username, recipient, text)
            result = {"ok": ok}
            if ok:
                result["message_id"] = message_id
            else:
                result["code"] = error
            self._send_raw(sock, make_message(MessageType.CHAT_RESULT, request_id=request_id, **result))
            return
        if kind in {MessageType.FILE_OFFER, MessageType.FILE_CHUNK, MessageType.FILE_END}:
            self._send_raw(sock, make_message(
                MessageType.ERROR, request_id=request_id, code="server_busy",
                message="File transfer handler is not available yet",
            ))
            return
        self._send_raw(sock, make_message(
            MessageType.ERROR, request_id=request_id, code="invalid_message", message="Unsupported message type"
        ))

    def _send(self, session: Session, message: dict[str, Any]) -> None:
        self._send_raw(session.sock, message, session.send_lock)

    def _send_raw(self, sock, message: dict[str, Any], lock: threading.Lock | None = None) -> None:
        frame = encode_frame(encode_message(message))
        if lock is None:
            session = self.sessions.get_socket(sock)
            lock = session.send_lock if session else None
        if lock is None:
            sock.sendall(frame)
        else:
            try:
                with lock:
                    sock.sendall(frame)
            except OSError:
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def _reap_idle_sessions(self) -> None:
        for stale in self.sessions.expired(self.idle_timeout):
            try:
                stale.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
