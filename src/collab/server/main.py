"""Command-line entry point for the collaboration server."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from collab.common.tls import create_server_context
from .auth import AuthService
from .discovery import DiscoveryServer
from .server import CollaborationServer
from .user_store import UserStore


def _env_path(name: str, default: str) -> str:
    value = os.environ.get(name, default)
    return str(Path(value).expanduser())


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the TLS collaboration server")
    parser.add_argument("--host", default=os.environ.get("COLLAB_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("COLLAB_PORT") or os.environ.get("COLLAB_TCP_PORT", "37021")),
    )
    parser.add_argument("--udp-port", type=int, default=int(os.environ.get("COLLAB_UDP_PORT", "37020")))
    parser.add_argument("--advertise-host", default=os.environ.get("COLLAB_ADVERTISE_HOST"))
    parser.add_argument(
        "--cert",
        default=_env_path("COLLAB_TLS_CERT", os.environ.get("COLLAB_CERT_FILE", "certs/server.crt")),
    )
    parser.add_argument(
        "--key",
        default=_env_path("COLLAB_TLS_KEY", os.environ.get("COLLAB_KEY_FILE", "certs/server.key")),
    )
    parser.add_argument("--database", default=_env_path("COLLAB_DATABASE", "data/users.sqlite3"))
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=int(os.environ.get("COLLAB_IDLE_TIMEOUT", "300")),
        help="idle TCP session timeout in seconds (default: 300)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    tls = create_server_context(args.cert, args.key)
    server = CollaborationServer(
        args.host,
        args.port,
        tls,
        AuthService(UserStore(args.database)),
        idle_timeout=args.idle_timeout,
    )
    discovery = DiscoveryServer(
        args.port, bind_host=args.host, udp_port=args.udp_port,
        advertise_host=args.advertise_host,
    )
    discovery.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.info("Shutting down server")
    finally:
        discovery.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
