"""UDP LAN discovery responder; it never creates authenticated sessions."""

from __future__ import annotations

import logging
import socket
import threading
import uuid

from collab.common.errors import ProtocolError
from collab.common.udp_protocol import decode_datagram, encode_datagram

log = logging.getLogger(__name__)


class DiscoveryServer:
    def __init__(
        self,
        tcp_port: int,
        *,
        bind_host: str = "0.0.0.0",
        udp_port: int = 37020,
        advertise_host: str | None = None,
        server_name: str = "collab",
    ) -> None:
        self.tcp_port, self.bind_host, self.udp_port = tcp_port, bind_host, udp_port
        self.advertise_host = advertise_host
        self.server_name = server_name
        self.server_id = str(uuid.uuid4())
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: socket.socket | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.bind_host, self.udp_port))
        sock.settimeout(1)
        self._socket = sock
        self._thread = threading.Thread(target=self.serve_forever, name="udp-discovery", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            self._socket = None
            sock.close()
            raise

    def serve_forever(self) -> None:
        sock = self._socket
        if sock is None:
            raise RuntimeError("call start() before serving discovery")
        log.info("UDP discovery listening on %s:%d", self.bind_host, self.udp_port)
        try:
            while not self._stop.is_set():
                try:
                    data, address = sock.recvfrom(2048)
                except socket.timeout:
                    continue
                except OSError:
                    if self._stop.is_set():
                        break
                    log.exception("UDP discovery socket failed")
                    break
                try:
                    request = decode_datagram(data)
                    kind = request["type"]
                    if kind == "discover":
                        host = self._announcement_host()
                        response = {
                            "v": 1, "type": "server_announcement",
                            "request_id": request["request_id"], "server_id": self.server_id,
                            "server_name": self.server_name, "host": host,
                            "tcp_port": self.tcp_port,
                        }
                    elif kind == "client_heartbeat":
                        response = {
                            "v": 1, "type": "heartbeat_ack",
                            "client_id": request["client_id"], "server_id": self.server_id,
                        }
                    else:
                        continue
                    sock.sendto(encode_datagram(response), address)
                except (ProtocolError, OSError):
                    log.debug("Ignored malformed UDP discovery datagram")
        finally:
            sock.close()
            if self._socket is sock:
                self._socket = None

    def _announcement_host(self) -> str:
        if self.advertise_host:
            return self.advertise_host
        if self.bind_host not in {"0.0.0.0", ""}:
            return self.bind_host
        return self._get_local_ip()

    @staticmethod
    def _get_local_ip() -> str:
        """Choose the local interface selected for outbound IPv4 traffic."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
                route_socket.connect(("8.8.8.8", 80))
                return route_socket.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def stop(self) -> None:
        self._stop.set()
        sock = self._socket
        if sock:
            try:
                sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=2)
