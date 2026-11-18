"""ServerController — manages the CollaborationServer + DiscoveryServer lifecycle.

The blocking ``CollaborationServer.serve_forever()`` runs on a background
thread. ``server_started`` is only emitted after the TCP listener is really
bound (``CollaborationServer.ready``), never speculatively.
"""
from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)

_READY_TIMEOUT_SEC = 10.0
_JOIN_TIMEOUT_SEC = 5.0


class ServerController(QObject):
    """Qt wrapper owning one server instance at a time."""

    server_started = Signal()
    server_stopped = Signal()
    server_error = Signal(str)
    log_message = Signal(str)
    client_count_changed = Signal(int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._server: Any = None
        self._discovery: Any = None
        self._tmpdir: tempfile.TemporaryDirectory | None = None
        self._running = False
        self._stop_requested = threading.Event()
        self._lock = threading.Lock()
        self.tcp_port: int | None = None

    # ------------------------------------------------------------------ API
    def is_running(self) -> bool:
        return self._running

    def client_count(self) -> int:
        server = self._server
        return len(server.sessions.snapshot()) if server is not None else 0

    def wait_until_ready(self, timeout: float = _READY_TIMEOUT_SEC) -> bool:
        server = self._server
        return bool(server is not None and server.ready.wait(timeout) and self._running)

    def start_server(self, config: dict) -> None:
        with self._lock:
            if self._running or (self._thread is not None and self._thread.is_alive()):
                self.server_error.emit("Server đang chạy hoặc đang khởi động.")
                return
            self._stop_requested.clear()
            self._thread = threading.Thread(
                target=self._run, args=(dict(config),), name="collab-server", daemon=True
            )
            self._thread.start()

    def stop_server(self) -> None:
        with self._lock:
            thread = self._thread
            if thread is None:
                return
            self._stop_requested.set()
        if self._discovery is not None:
            self._safe(self._discovery.stop)
        if self._server is not None:
            self._safe(self._server.shutdown)
        thread.join(timeout=_JOIN_TIMEOUT_SEC)
        self._cleanup()
        self.server_stopped.emit()

    # ------------------------------------------------------------- internals
    @staticmethod
    def _safe(fn) -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - shutdown must never raise into the UI
            log.debug("ignored error during shutdown", exc_info=True)

    def _cleanup(self) -> None:
        self._running = False
        self._server = None
        self._discovery = None
        self._thread = None
        self.tcp_port = None
        if self._tmpdir is not None:
            self._safe(self._tmpdir.cleanup)
            self._tmpdir = None

    def _fail(self, message: str) -> None:
        self._running = False
        self.server_error.emit(message)

    def _build(self, config: dict):
        from collab.common.tls import create_server_context
        from collab.server.auth import AuthService
        from collab.server.server import CollaborationServer
        from collab.server.user_store import UserStore

        try:
            tls = create_server_context(str(config.get("cert", "")), str(config.get("key", "")))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"Chứng chỉ/khóa TLS không hợp lệ: {exc}") from exc
        except Exception as exc:  # ssl.SSLError
            raise RuntimeError(f"Chứng chỉ/khóa TLS không hợp lệ: {exc}") from exc

        database = str(config.get("database") or "data/users.sqlite3")
        if database == ":memory:":
            self._tmpdir = tempfile.TemporaryDirectory(prefix="collab-gui-db-")
            database = str(Path(self._tmpdir.name) / "users.sqlite3")
        else:
            Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)
        users = UserStore(database)
        return CollaborationServer(
            str(config.get("host", "0.0.0.0")),
            int(config.get("port", 37021)),
            tls,
            AuthService(users),
            idle_timeout=int(config.get("idle_timeout", 90)),
            auth_timeout=float(config.get("auth_timeout", 60)),
        )

    def _run(self, config: dict) -> None:
        from collab.server.discovery import DiscoveryServer

        try:
            server = self._build(config)
        except Exception as exc:  # noqa: BLE001
            self._fail(str(exc))
            return
        self._server = server

        threading.Thread(
            target=self._announce_when_ready,
            args=(server, config, DiscoveryServer),
            name="collab-server-ready",
            daemon=True,
        ).start()
        try:
            server.serve_forever()
        except OSError as exc:
            port = config.get("port")
            self._fail(f"Không thể mở cổng TCP {port}: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._fail(f"Server dừng đột ngột: {exc}")
            return
        finally:
            if self._discovery is not None:
                self._safe(self._discovery.stop)
        if not self._stop_requested.is_set():
            # accept loop died without a stop request
            self._running = False
            self.server_stopped.emit()

    def _announce_when_ready(self, server, config: dict, discovery_cls) -> None:
        if not server.ready.wait(_READY_TIMEOUT_SEC) or server.startup_error is not None:
            return  # _run reports the bind failure
        self.tcp_port = server.bound_port
        udp_port = int(config.get("udp_port") or 0)
        if udp_port:
            try:
                discovery = discovery_cls(
                    server.bound_port,
                    bind_host=str(config.get("host", "0.0.0.0")),
                    udp_port=udp_port,
                    advertise_host=config.get("advertise_host") or None,
                )
                discovery.start()
                self._discovery = discovery
                self.log_message.emit(f"UDP discovery đang lắng nghe cổng {udp_port}")
            except Exception as exc:  # noqa: BLE001
                self.log_message.emit(f"Cảnh báo: UDP discovery không khởi động được: {exc}")
        self._running = True
        self.log_message.emit(
            f"Server đang lắng nghe tại {config.get('host', '0.0.0.0')}:{server.bound_port}"
        )
        self.server_started.emit()
        last = -1
        while not self._stop_requested.wait(1.0):
            count = len(server.sessions.snapshot())
            if count != last:
                last = count
                self.client_count_changed.emit(count)
