"""Client UDP server discovery and non-authenticating heartbeat helpers."""

from __future__ import annotations

import socket
import threading
import time
import uuid
from typing import Any

from collab.common.errors import ProtocolError
from collab.common.udp_protocol import decode_datagram, encode_datagram


def discover_server(*, udp_port: int = 37020, broadcast: bool = False,
                    target_host: str = "127.0.0.1", timeout: float = 1.5,
                    attempts: int = 2) -> dict[str, Any] | None:
    """Return the first valid announcement matching this request, if any."""
    request_id = str(uuid.uuid4())
    payload = encode_datagram({"v": 1, "type": "discover", "request_id": request_id})
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if broadcast:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        for _ in range(max(1, attempts)):
            sock.sendto(payload, (target_host, udp_port))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                sock.settimeout(remaining)
                try:
                    packet, _ = sock.recvfrom(2048)
                except socket.timeout:
                    break
                try:
                    reply = decode_datagram(packet)
                except ProtocolError:
                    continue
                if reply.get("type") == "server_announcement" and reply.get("request_id") == request_id:
                    return reply
    return None


class UDPHeartbeat:
    """Send advisory UDP heartbeats while connected; these never authenticate."""

    def __init__(self, host: str, port: int = 37020, *, interval: float = 30.0) -> None:
        self.host, self.port, self.interval = host, port, interval
        self.client_id = str(uuid.uuid4())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._thread = threading.Thread(target=self._run, name="collab-udp-heartbeat", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self._socket is not None
        payload = encode_datagram({"v": 1, "type": "client_heartbeat", "client_id": self.client_id})
        while not self._stop.is_set():
            try:
                self._socket.sendto(payload, (self.host, self.port))
            except OSError:
                if not self._stop.is_set():
                    return
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()
        if self._socket:
            self._socket.close()
            self._socket = None
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)
