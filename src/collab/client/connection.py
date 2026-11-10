"""Thread-safe TCP/TLS client with correlated requests and server events."""

from __future__ import annotations

import logging
import socket
import ssl
import threading
from typing import Any, Callable

from collab.common.errors import ProtocolError
from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import decode_message, encode_message, make_message, new_request_id

log = logging.getLogger(__name__)


class ClientConnectionError(ConnectionError):
    """Raised when the secure server connection cannot be used."""


class ClientConnection:
    def __init__(
        self,
        host: str,
        port: int,
        tls_context: ssl.SSLContext,
        *,
        server_hostname: str | None = None,
        timeout: float = 15.0,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.host, self.port, self.tls_context = host, port, tls_context
        self.server_hostname, self.timeout = server_hostname or host, timeout
        self.on_event = on_event
        self.sock: ssl.SSLSocket | None = None
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[str, tuple[threading.Event, dict[str, Any] | None]] = {}
        self._closed = threading.Event()
        self._keepalive_stop = threading.Event()
        self._reader: threading.Thread | None = None
        self._keepalive: threading.Thread | None = None

    def connect(self) -> dict[str, Any]:
        raw = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(raw, server_hostname=self.server_hostname)
            self.sock.settimeout(self.timeout)
            req_id = new_request_id()
            hello = make_message("hello", request_id=req_id, client="collab-cli", client_version="1.0")
            self.sock.sendall(encode_frame(encode_message(hello)))
            welcome = decode_message(recv_frame(self.sock))
            if welcome.get("type") != "welcome" or welcome.get("request_id") != req_id:
                raise ClientConnectionError("Server did not complete the protocol handshake")
            self.sock.settimeout(None)
            self._reader = threading.Thread(
                target=self._receive_loop,
                name="collab-client-receiver",
                daemon=True,
            )
            self._reader.start()
            interval = max(5, int(welcome.get("heartbeat_interval_sec", 30)))
            self._keepalive = threading.Thread(
                target=self._keepalive_loop,
                args=(interval,),
                name="collab-tcp-keepalive",
                daemon=True,
            )
            self._keepalive.start()
            return welcome
        except BaseException:
            raw_to_close = self.sock or raw
            try:
                raw_to_close.close()
            except OSError:
                pass
            self.sock = None
            raise

    def request(self, kind: str, *, timeout: float = 30.0, **fields: Any) -> dict[str, Any]:
        sock = self.sock
        if sock is None or self._closed.is_set():
            raise ClientConnectionError("Not connected to a server")
        request_id = new_request_id()
        event = threading.Event()
        with self._pending_lock:
            self._pending[request_id] = (event, None)
        message = make_message(kind, request_id=request_id, **fields)
        try:
            with self._send_lock:
                sock.sendall(encode_frame(encode_message(message)))
        except (OSError, ssl.SSLError) as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            self._fail(exc)
            raise ClientConnectionError("Connection to server was lost") from exc
        if not event.wait(timeout):
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"Server did not answer {kind} within {timeout:g} seconds")
        with self._pending_lock:
            item = self._pending.pop(request_id, None)
        if item is None or item[1] is None:
            raise ClientConnectionError("Connection to server was lost")
        return item[1]

    def _receive_loop(self) -> None:
        try:
            while not self._closed.is_set():
                message = decode_message(recv_frame(self.sock))
                request_id = message.get("request_id")
                delivered = False
                if request_id:
                    with self._pending_lock:
                        pending = self._pending.get(request_id)
                        if pending:
                            self._pending[request_id] = (pending[0], message)
                            pending[0].set()
                            delivered = True
                if not delivered and self.on_event:
                    try:
                        self.on_event(message)
                    except Exception:  # noqa: BLE001
                        log.exception("Unhandled error inside client event callback")
        except (OSError, ssl.SSLError, EOFError, ValueError, ProtocolError) as exc:
            if not self._closed.is_set():
                self._fail(exc)

    def _keepalive_loop(self, interval: int) -> None:
        while not self._keepalive_stop.wait(interval) and self.connected:
            try:
                self.request("ping", timeout=min(interval, 10))
            except (ClientConnectionError, TimeoutError, OSError):
                self._fail(ClientConnectionError("TCP heartbeat failed"))
                return

    def _fail(self, cause: BaseException) -> None:
        with self._state_lock:
            if self._closed.is_set():
                return
            self._closed.set()
            sock, self.sock = self.sock, None
        if sock:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for event, _ in pending:
            event.set()
        if self.on_event:
            try:
                self.on_event({"type": "connection_lost", "reason": str(cause)})
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._keepalive_stop.set()
        try:
            self.request("logout", timeout=3)
        except (ClientConnectionError, TimeoutError, OSError):
            pass
        self._fail(ClientConnectionError("Client closed the connection"))
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=2)
        if self._keepalive and self._keepalive is not threading.current_thread():
            self._keepalive.join(timeout=2)

    @property
    def connected(self) -> bool:
        return self.sock is not None and not self._closed.is_set()
