"""Background QRunnable workers — every blocking network call runs here, never on the UI thread."""
from __future__ import annotations

import logging
import socket
import ssl
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal

log = logging.getLogger(__name__)


def friendly_error(exc: BaseException) -> str:
    """Translate low-level exceptions into actionable Vietnamese messages."""
    if isinstance(exc, ssl.SSLCertVerificationError):
        detail = getattr(exc, "verify_message", "") or str(exc)
        if "IP address mismatch" in str(exc) or "Hostname mismatch" in str(exc):
            return (
                "Địa chỉ server không khớp với SAN trong chứng chỉ TLS. "
                "Hãy tạo lại chứng chỉ có SAN chứa đúng IP/hostname này, rồi chọn lại file CA. "
                f"({detail})"
            )
        return (
            "Chứng chỉ của server không đáng tin cậy. Hãy chọn file CA/chứng chỉ của server "
            f"(không thể tắt xác minh). ({detail})"
        )
    if isinstance(exc, ssl.SSLError):
        return f"Lỗi TLS khi kết nối: {exc}"
    if isinstance(exc, ConnectionRefusedError):
        return "Server từ chối kết nối. Kiểm tra server đã chạy và đúng host/cổng TCP."
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "Server không phản hồi (hết thời gian chờ)."
    if isinstance(exc, socket.gaierror):
        return "Không phân giải được tên máy chủ. Kiểm tra lại host/IP."
    return str(exc) or exc.__class__.__name__


class WorkerSignals(QObject):
    finished = Signal()
    error = Signal(str)
    result = Signal(object)


class _BaseWorker(QRunnable):
    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    def _do(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def run(self) -> None:
        try:
            outcome = self._do()
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never swallowed
            log.debug("worker %s failed", type(self).__name__, exc_info=True)
            self.signals.error.emit(friendly_error(exc))
        else:
            self.signals.result.emit(outcome)
        finally:
            self.signals.finished.emit()


class ConnectWorker(_BaseWorker):
    """Open the TLS connection + protocol handshake. Result: ``(connection, welcome)``."""

    def __init__(
        self,
        host: str,
        port: int,
        tls_context: ssl.SSLContext,
        download_dir: str,
        on_event: Callable[[dict], None] | None = None,
    ) -> None:
        super().__init__()
        self.host, self.port, self.tls_context = host, port, tls_context
        self.download_dir, self.on_event = download_dir, on_event

    def _do(self) -> Any:
        from collab.client.connection import ClientConnection

        connection = ClientConnection(
            self.host, self.port, self.tls_context, on_event=self.on_event
        )
        welcome = connection.connect()
        return connection, welcome


class AuthWorker(_BaseWorker):
    """``action`` is ``"login"`` or ``"register"``. Result: the server response dict."""

    def __init__(self, connection: Any, action: str, username: str, password: str) -> None:
        super().__init__()
        if action not in {"login", "register"}:
            raise ValueError("action must be 'login' or 'register'")
        self.connection, self.action = connection, action
        self.username, self._password = username, password

    def _do(self) -> Any:
        return self.connection.request(
            self.action, username=self.username, password=self._password
        )


class ChatWorker(_BaseWorker):
    def __init__(self, connection: Any, to: str | None, text: str) -> None:
        super().__init__()
        self.connection, self.to, self.text = connection, to, text

    def _do(self) -> Any:
        return self.connection.request("chat_send", to=self.to, text=self.text)


class DiscoveryWorker(_BaseWorker):
    """UDP discovery only locates a server; TLS verification still happens on connect."""

    def __init__(
        self,
        udp_port: int,
        broadcast: bool = False,
        target_host: str = "127.0.0.1",
        timeout: float = 2.0,
    ) -> None:
        super().__init__()
        self.udp_port, self.broadcast = udp_port, broadcast
        self.target_host, self.timeout = target_host, timeout

    def _do(self) -> Any:
        from collab.client.discovery import discover_server

        return discover_server(
            udp_port=self.udp_port,
            broadcast=self.broadcast,
            target_host=self.target_host,
            timeout=self.timeout,
            attempts=2,
        )


class FileSendWorker(_BaseWorker):
    """Hash the file and send the offer. Result: the :class:`TransferManifest`."""

    def __init__(self, sender: Any, path: str, recipient: str) -> None:
        super().__init__()
        self.sender, self.path, self.recipient = sender, path, recipient

    def _do(self) -> Any:
        return self.sender.start_send(self.path, self.recipient)


class CallWorker(_BaseWorker):
    """Run an arbitrary blocking callable (accept / reject / cancel / logout)."""

    def __init__(self, fn: Callable[..., Any], *args: Any) -> None:
        super().__init__()
        self.fn, self.args = fn, args

    def _do(self) -> Any:
        return self.fn(*self.args)
