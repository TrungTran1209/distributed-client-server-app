"""Concurrent TCP/TLS server for authentication, presence, chat, and file relay."""

from __future__ import annotations

from datetime import datetime
import logging
import os
import socket
import ssl
import threading
import time
import uuid
from typing import Any, Callable

from collab.common.errors import ProtocolError
from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import (
    MAX_CHAT_LENGTH,
    MessageType,
    decode_message,
    encode_message,
    make_message,
    normalize_username,
)
from .auth import AuthService
from .message_store import MessageStore
from .ratelimit import SlidingWindowLimiter, TokenBucketLimiter
from .router import MessageRouter
from .sessions import Session, SessionRegistry
from .transfer_coordinator import FILE_REQUEST_TYPES, TransferCoordinator

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
        auth_timeout: float = 60,
        send_timeout: float = 15.0,
        max_auth_failures: int = 5,
        register_limit_per_ip: int = 30,
        register_window_sec: float = 60.0,
        chat_rate: float = 10.0,
        chat_burst: int = 20,
        message_store: MessageStore | None = None,
        on_trace: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.host, self.port = host, port
        self.tls_context, self.auth = tls_context, auth
        self.on_trace = on_trace
        self.max_clients, self.idle_timeout = max_clients, idle_timeout
        self.auth_timeout, self.send_timeout = float(auth_timeout), float(send_timeout)
        self.max_auth_failures = max(1, int(max_auth_failures))
        self._register_limiter = SlidingWindowLimiter(
            limit=register_limit_per_ip,
            window_sec=register_window_sec,
        )
        self._chat_limiter = TokenBucketLimiter(rate=chat_rate, burst=chat_burst)
        self.sessions = SessionRegistry()
        user_store = getattr(auth, "users", None)
        if message_store is None and user_store is not None and hasattr(user_store, "path"):
            message_store = MessageStore(user_store.path)
        self.message_store = message_store
        self.router = MessageRouter(
            self.sessions,
            self._send,
            user_store=user_store,
            message_store=self.message_store,
        )
        self.transfers = TransferCoordinator(
            self.sessions,
            self._send,
            on_trace=self._forward_trace,
        )
        self._stop = threading.Event()
        self._listener: socket.socket | None = None
        # Readiness signalling for embedders (e.g. the desktop GUI): `ready` is
        # set once the listener is bound or startup failed (`startup_error`).
        self.ready = threading.Event()
        self.startup_error: OSError | None = None
        self.bound_port: int | None = None
        self._workers: set[threading.Thread] = set()
        self._workers_lock = threading.Lock()

    def _forward_trace(self, event: dict[str, Any]) -> None:
        if self.on_trace is None:
            return
        payload = {"ts": datetime.now().strftime("%H:%M:%S.%f")[:-3], **event}
        try:
            self.on_trace(payload)
        except Exception:  # noqa: BLE001
            pass

    def _emit_trace(self, category: str, action: str, **fields: Any) -> None:
        self._forward_trace({"category": category, "action": action, **fields})

    def serve_forever(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            if os.name != "nt":
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind((self.host, self.port))
            listener.listen(64)
        except OSError as exc:
            listener.close()
            self.startup_error = exc
            self.ready.set()
            raise
        listener.settimeout(1.0)
        self._listener = listener
        self.bound_port = listener.getsockname()[1]
        self.ready.set()
        next_reap = time.monotonic() + 1.0
        log.info("TLS server listening on %s:%d", *listener.getsockname()[:2])
        try:
            while not self._stop.is_set():
                if time.monotonic() >= next_reap:
                    self._reap_idle_sessions()
                    next_reap = time.monotonic() + 1.0
                try:
                    raw, address = listener.accept()
                except socket.timeout:
                    continue
                except (ConnectionResetError, ConnectionAbortedError):
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    log.exception("TCP listener failed")
                    break
                self._spawn_client_worker(raw, address)
        finally:
            listener.close()
            self._listener = None

    def _spawn_client_worker(self, raw: socket.socket, address: tuple[Any, ...]) -> None:
        with self._workers_lock:
            active = sum(worker.is_alive() for worker in self._workers)
        if active >= self.max_clients:
            raw.close()
            return
        worker = threading.Thread(
            target=self._handle_connection,
            args=(raw, address),
            name=f"client-{address[0]}:{address[1]}",
            daemon=True,
        )
        with self._workers_lock:
            self._workers.add(worker)
        try:
            worker.start()
        except RuntimeError:
            with self._workers_lock:
                self._workers.discard(worker)
            raw.close()

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
            raw.settimeout(15)
            tls_sock = self.tls_context.wrap_socket(raw, server_side=True)
            self._connection_loop(tls_sock, address)
        except (ssl.SSLError, OSError, EOFError, ProtocolError) as exc:
            log.info("Client connection ended (%s)", type(exc).__name__)
        finally:
            sock = tls_sock or raw
            session = self.sessions.remove(sock)
            if session:
                self._chat_limiter.remove(session.session_id)
                self.transfers.on_disconnect(session.username)
                self.router.broadcast_presence(MessageType.PRESENCE_OFFLINE, session.username)
                self._emit_trace("SESSION", "disconnect", actor=session.username, target="-")
            try:
                sock.close()
            except OSError:
                pass
            current = threading.current_thread()
            with self._workers_lock:
                self._workers.discard(current)

    def _connection_loop(self, sock: ssl.SSLSocket, address: tuple[Any, ...]) -> None:
        greeted = False
        auth_deadline = time.monotonic() + self.auth_timeout
        auth_failures = 0
        while not self._stop.is_set():
            outcome = self._recv_next_request(sock, auth_deadline)
            if outcome is None:
                return
            request, session = outcome
            request_id = request.get("request_id")
            if not greeted:
                if not self._handle_greeting(sock, request["type"], request_id):
                    return
                greeted = True
                continue
            try:
                keep_open, auth_failures = self._dispatch(
                    sock, address, request, session, auth_failures
                )
                if not keep_open:
                    return
                if session is not None and self.sessions.get_socket(sock) is None:
                    auth_deadline = time.monotonic() + self.auth_timeout
                    auth_failures = 0
            except ProtocolError as exc:
                self._send_raw(
                    sock,
                    make_message(
                        MessageType.ERROR,
                        request_id=request_id,
                        code="invalid_message",
                        message=str(exc),
                    ),
                )

    def _recv_next_request(
        self, sock: ssl.SSLSocket, auth_deadline: float
    ) -> tuple[dict[str, Any], Session | None] | None:
        if self.sessions.get_socket(sock) is None:
            remaining = auth_deadline - time.monotonic()
            if remaining <= 0:
                return None
            sock.settimeout(remaining)
        else:
            sock.settimeout(self.idle_timeout)
        try:
            request = decode_message(recv_frame(sock))
        except socket.timeout:
            return None
        session = self.sessions.get_socket(sock)
        if session is None and time.monotonic() > auth_deadline:
            return None
        if session:
            self.sessions.touch(sock)
        return request, session

    def _handle_greeting(self, sock: ssl.SSLSocket, kind: str, request_id: str | None) -> bool:
        if kind != MessageType.HELLO:
            self._send_raw(
                sock,
                make_message(
                    MessageType.ERROR,
                    request_id=request_id,
                    code="invalid_message",
                    message="Send hello first",
                ),
            )
            return False
        self._send_raw(
            sock,
            make_message(
                MessageType.WELCOME,
                request_id=request_id,
                protocol_version=1,
                server_name="collab",
                heartbeat_interval_sec=30,
            ),
        )
        return True

    def _dispatch(
        self,
        sock,
        address,
        request,
        session: Session | None,
        auth_failures: int,
    ) -> tuple[bool, int]:
        kind = request["type"]
        request_id = request.get("request_id")
        if kind == MessageType.PING:
            self._send_raw(sock, make_message(MessageType.PONG, request_id=request_id))
            return True, auth_failures
        if session is None:
            return self._dispatch_unauthenticated(sock, address, request, request_id, auth_failures)
        self._dispatch_authenticated(sock, request, session, request_id)
        return True, 0

    def _dispatch_unauthenticated(
        self,
        sock,
        address,
        request,
        request_id: str | None,
        auth_failures: int,
    ) -> tuple[bool, int]:
        kind = request["type"]
        if kind == MessageType.REGISTER:
            peer_ip = str(address[0])
            if not self._register_limiter.allow(peer_ip):
                self._send_raw(
                    sock,
                    make_message(
                        MessageType.REGISTER_RESULT,
                        request_id=request_id,
                        ok=False,
                        code="rate_limited",
                    ),
                )
                return True, auth_failures
            reg_name = ""
            try:
                ok, reg_name = self.auth.register(request.get("username"), request.get("password"))
                response: dict[str, Any] = {"ok": ok}
                if not ok:
                    response["code"] = "username_taken"
            except ProtocolError as exc:
                ok = False
                response = {"ok": False, "code": "invalid_message", "message": str(exc)}
            self._send_raw(sock, make_message(MessageType.REGISTER_RESULT, request_id=request_id, **response))
            if ok and reg_name:
                self._emit_trace("AUTH", "register", actor=reg_name, target=peer_ip)
            return True, auth_failures
        if kind == MessageType.LOGIN:
            return self._handle_login(sock, address, request, request_id, auth_failures)
        self._send_raw(
            sock,
            make_message(
                MessageType.ERROR,
                request_id=request_id,
                code="unauthorized",
                message="Login required",
            ),
        )
        return True, auth_failures

    def _handle_login(
        self,
        sock,
        address,
        request,
        request_id: str | None,
        auth_failures: int,
    ) -> tuple[bool, int]:
        try:
            ok, username = self.auth.login(request.get("username"), request.get("password"))
        except ProtocolError:
            ok, username = False, ""
        if not ok:
            next_failures = auth_failures + 1
            throttled = next_failures >= self.max_auth_failures
            self._send_raw(
                sock,
                make_message(
                    MessageType.LOGIN_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="rate_limited" if throttled else "invalid_credentials",
                ),
            )
            return not throttled, next_failures
        new_session = Session(username, sock, str(address[0]), int(address[1]), str(uuid.uuid4()))
        if not self.sessions.add(new_session):
            self._send_raw(
                sock,
                make_message(
                    MessageType.LOGIN_RESULT,
                    request_id=request_id,
                    ok=False,
                    code="already_online",
                ),
            )
            return True, auth_failures
        self._send_raw(
            sock,
            make_message(
                MessageType.LOGIN_RESULT,
                request_id=request_id,
                ok=True,
                username=username,
                session_id=new_session.session_id,
            ),
        )
        self._send_raw(
            sock,
            make_message(
                MessageType.USER_LIST,
                users=self.router.user_list(),
                directory=self.router.directory_list(),
            ),
        )
        self.router.broadcast_presence(MessageType.PRESENCE_ONLINE, username, exclude=sock)
        self._emit_trace("AUTH", "login", actor=username, target=f"{address[0]}:{address[1]}")
        return True, 0

    def _dispatch_authenticated(self, sock, request, session: Session, request_id: str | None) -> None:
        kind = request["type"]
        if kind == MessageType.LOGOUT:
            self._send_raw(sock, make_message(MessageType.LOGOUT_RESULT, request_id=request_id, ok=True))
            removed = self.sessions.remove(sock)
            if removed:
                self._chat_limiter.remove(removed.session_id)
                self.transfers.on_disconnect(removed.username)
                self.router.broadcast_presence(MessageType.PRESENCE_OFFLINE, removed.username)
                self._emit_trace("SESSION", "logout", actor=removed.username, target="-")
            return
        if kind == MessageType.CHAT_SEND:
            self._handle_chat(sock, request, session, request_id)
            return
        if kind == MessageType.USER_DIRECTORY:
            self._send_raw(
                sock,
                make_message(
                    MessageType.USER_DIRECTORY_RESULT,
                    request_id=request_id,
                    ok=True,
                    directory=self.router.directory_list(),
                ),
            )
            return
        if kind == MessageType.CHAT_HISTORY:
            raw_limit = request.get("limit", 300)
            limit = int(raw_limit) if type(raw_limit) is int else 300
            messages = (
                self.message_store.get_history_for_user(session.username, limit=limit)
                if self.message_store is not None
                else []
            )
            self._send_raw(
                sock,
                make_message(
                    MessageType.CHAT_HISTORY_RESULT,
                    request_id=request_id,
                    ok=True,
                    messages=messages,
                ),
            )
            self._emit_trace("CHAT", "chat_history", actor=session.username, target="-", count=len(messages))
            return
        if kind in FILE_REQUEST_TYPES:
            response = self.transfers.handle_request(session, request)
            self._send_raw(sock, response)
            return
        self._send_raw(
            sock,
            make_message(
                MessageType.ERROR,
                request_id=request_id,
                code="invalid_message",
                message="Unsupported message type",
            ),
        )

    def _handle_chat(self, sock, request, session: Session, request_id: str | None) -> None:
        recipient = request.get("to")
        text = request.get("text")
        if recipient is not None:
            if not isinstance(recipient, str):
                raise ProtocolError("to must be a username or null")
            recipient = normalize_username(recipient)
        if not isinstance(text, str) or not text or len(text) > MAX_CHAT_LENGTH:
            raise ProtocolError("text must contain 1-4000 characters")
        if not self._chat_limiter.allow(session.session_id):
            self._send_raw(
                sock,
                make_message(MessageType.CHAT_RESULT, request_id=request_id, ok=False, code="rate_limited"),
            )
            return
        result = self.router.route_chat(session.username, recipient, text)
        if result.get("ok"):
            action = (
                "chat_offline"
                if result.get("queued_offline")
                else ("chat_broadcast" if recipient is None else "chat_direct")
            )
            self._emit_trace(
                "CHAT",
                action,
                actor=session.username,
                target=recipient or "*",
                chars=len(text),
            )
        self._send_raw(sock, make_message(MessageType.CHAT_RESULT, request_id=request_id, **result))

    def _send(self, session: Session, message: dict[str, Any]) -> None:
        frame = encode_frame(encode_message(message))
        if not session.send_lock.acquire(timeout=self.send_timeout):
            self._close_peer_socket(session.sock)
            return
        session.send_started_at = time.monotonic()
        try:
            session.sock.sendall(frame)
        except OSError:
            self._close_peer_socket(session.sock)
        finally:
            session.send_started_at = None
            session.send_lock.release()

    def _send_raw(self, sock, message: dict[str, Any]) -> None:
        session = self.sessions.get_socket(sock)
        if session is not None:
            self._send(session, message)
            return
        sock.sendall(encode_frame(encode_message(message)))

    def _reap_idle_sessions(self) -> None:
        self.transfers.reap_expired()
        stale_sessions = (
            *self.sessions.expired(self.idle_timeout),
            *self.sessions.stalled_sends(self.send_timeout),
        )
        for stale in stale_sessions:
            self._close_peer_socket(stale.sock)

    @staticmethod
    def _close_peer_socket(sock: Any) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
