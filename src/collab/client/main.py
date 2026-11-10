"""CLI entry point for a TLS collaboration client."""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys
from pathlib import Path

from collab.common.tls import create_client_context
from .commands import CommandLine
from .connection import ClientConnection, ClientConnectionError
from .discovery import UDPHeartbeat, discover_server


def _path(value: str | None) -> str | None:
    return str(Path(value).expanduser()) if value else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Connect to the TLS collaboration server")
    parser.add_argument("--host", default=os.environ.get("COLLAB_SERVER_HOST"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("COLLAB_SERVER_PORT", "37021")))
    parser.add_argument("--udp-port", type=int, default=int(os.environ.get("COLLAB_UDP_PORT", "37020")))
    parser.add_argument("--ca", default=os.environ.get("COLLAB_TLS_CA_FILE"))
    parser.add_argument("--discover", action="store_true", help="find a server via UDP before connecting")
    parser.add_argument("--broadcast", action="store_true", help="send discovery to the LAN broadcast address")
    parser.add_argument(
        "--discover-host",
        default=os.environ.get("COLLAB_DISCOVERY_HOST", "127.0.0.1"),
        help="UDP unicast destination for discovery (default: localhost)",
    )
    parser.add_argument("--timeout", type=float, default=2.5, help="UDP discovery timeout in seconds")
    parser.add_argument(
        "--download-dir",
        default=os.environ.get("COLLAB_DOWNLOAD_DIR", "downloads"),
        help="directory where verified incoming files are saved",
    )
    parser.add_argument(
        "--auto-accept",
        action="store_true",
        help="automatically accept valid incoming file offers",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    host, port = args.host, args.port
    if args.discover or not host:
        announcement = discover_server(
            udp_port=args.udp_port,
            broadcast=args.broadcast,
            target_host=args.discover_host,
            timeout=args.timeout,
            attempts=2,
        )
        if announcement:
            host, port = announcement["host"], announcement["tcp_port"]
            print(f"Tìm thấy {announcement['server_name']} tại {host}:{port}")
        elif not host:
            parser.error("không tìm thấy server UDP; chỉ định --host hoặc bật server discovery")
        else:
            print("Không tìm thấy server UDP; dùng địa chỉ host/port đã cấu hình.")

    assert host is not None
    try:
        tls_context = create_client_context(_path(args.ca))
        cli: CommandLine
        connection = ClientConnection(
            host,
            port,
            tls_context,
            on_event=lambda event: cli.show_event(event),
        )
        cli = CommandLine(
            connection,
            output=sys.stdout,
            download_dir=Path(args.download_dir).expanduser(),
            auto_accept=args.auto_accept,
        )
        welcome = connection.connect()
        interval = max(5, int(welcome.get("heartbeat_interval_sec", 30)))
        heartbeat = UDPHeartbeat(host, args.udp_port, interval=interval)
        heartbeat.start()
        cli.heartbeat = heartbeat
        try:
            cli.run()
        finally:
            heartbeat.stop()
    except (OSError, socket.timeout, ClientConnectionError) as exc:
        print(f"Không thể kết nối an toàn tới {host}:{port}: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except Exception as exc:
        # ssl.SSLCertVerificationError and configuration errors get a direct,
        # actionable message without disabling certificate validation.
        print(f"Kết nối thất bại: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
