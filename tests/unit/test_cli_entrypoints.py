import io
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from collab.client import main as client_main
from collab.client.commands import CommandLine
from collab.client.connection import ClientConnectionError
from collab.common.errors import TransferError
from collab.common.protocol import MessageType
from collab.server import main as server_main
from collab.transfer.manifest import TransferProgress
from collab.transfer.receiver import FileReceiver


class CliEntrypointsAndEdgeCaseTests(unittest.TestCase):
    def test_server_main_parses_flags_env_and_shuts_down_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "users.sqlite3")
            fake_server = MagicMock()
            fake_server.serve_forever.side_effect = KeyboardInterrupt
            fake_discovery = MagicMock()

            env = {
                "COLLAB_IDLE_TIMEOUT": "120",
                "COLLAB_AUTH_TIMEOUT": "45",
            }
            argv = [
                "collab-server",
                "--host",
                "127.0.0.1",
                "--port",
                "37999",
                "--udp-port",
                "37998",
                "--advertise-host",
                "127.0.0.1",
                "--cert",
                "certs/server.crt",
                "--key",
                "certs/server.key",
                "--database",
                db_path,
            ]
            with (
                patch.dict(os.environ, env, clear=False),
                patch("sys.argv", argv),
                patch("collab.server.main.create_server_context", return_value=MagicMock()),
                patch("collab.server.main.CollaborationServer", return_value=fake_server) as cls_srv,
                patch("collab.server.main.DiscoveryServer", return_value=fake_discovery) as cls_disc,
            ):
                server_main.main()

            self.assertEqual(cls_srv.call_args.kwargs["idle_timeout"], 120)
            self.assertEqual(cls_srv.call_args.kwargs["auth_timeout"], 45)
            self.assertEqual(cls_disc.call_args.kwargs["advertise_host"], "127.0.0.1")
            fake_discovery.start.assert_called_once()
            fake_discovery.stop.assert_called_once()
            fake_server.shutdown.assert_called_once()

    def test_client_main_sanitizes_udp_announcement_and_runs_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_conn = MagicMock()
            fake_conn.connect.return_value = {"heartbeat_interval_sec": 30}
            fake_hb = MagicMock()
            fake_cli = MagicMock()
            stdout = io.StringIO()

            malicious_announcement = {
                "server_name": "collab\x1b[31m-evil",
                "host": "127.0.0.1\x07",
                "tcp_port": 37021,
            }
            argv = [
                "collab-client",
                "--discover",
                "--download-dir",
                tmp,
                "--auto-accept",
            ]
            with (
                patch("sys.argv", argv),
                patch("sys.stdout", stdout),
                patch("collab.client.main.discover_server", return_value=malicious_announcement),
                patch("collab.client.main.create_client_context", return_value=MagicMock()),
                patch("collab.client.main.ClientConnection", return_value=fake_conn),
                patch("collab.client.main.CommandLine", return_value=fake_cli),
                patch("collab.client.main.UDPHeartbeat", return_value=fake_hb),
            ):
                client_main.main()

            printed = stdout.getvalue()
            self.assertNotIn("\x1b", printed)
            self.assertNotIn("\x07", printed)
            self.assertIn("collab[31m-evil", printed)
            fake_hb.start.assert_called_once()
            fake_cli.run.assert_called_once()
            fake_hb.stop.assert_called_once()

    def test_client_main_handles_missing_discovery_and_connection_errors(self):
        stderr = io.StringIO()
        # 1. Missing --host and discovery returns None -> parser.error (SystemExit 2)
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("sys.argv", ["collab-client"]),
            patch("sys.stderr", stderr),
            patch("collab.client.main.discover_server", return_value=None),
        ):
            with self.assertRaises(SystemExit) as ctx_missing:
                client_main.main()
            self.assertEqual(ctx_missing.exception.code, 2)

        # 2. Fallback to explicit --host when discovery returns None, then ClientConnectionError -> SystemExit 1
        fake_conn = MagicMock()
        fake_conn.connect.side_effect = ClientConnectionError("handshake failed")
        stdout = io.StringIO()
        with (
            patch("sys.argv", ["collab-client", "--host", "127.0.0.1", "--discover", "--ca", "~/ca.crt"]),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
            patch("collab.client.main.discover_server", return_value=None),
            patch("collab.client.main.create_client_context", return_value=MagicMock()),
            patch("collab.client.main.ClientConnection", return_value=fake_conn),
            patch("collab.client.main.CommandLine", return_value=MagicMock()),
        ):
            with self.assertRaises(SystemExit) as ctx_conn:
                client_main.main()
            self.assertEqual(ctx_conn.exception.code, 1)
        self.assertIn("dùng địa chỉ host/port đã cấu hình", stdout.getvalue())

        # 3. Generic TLS/config error -> SystemExit 1
        with (
            patch("sys.argv", ["collab-client", "--host", "127.0.0.1"]),
            patch("sys.stderr", stderr),
            patch("collab.client.main.create_client_context", side_effect=ValueError("bad cert")),
        ):
            with self.assertRaises(SystemExit) as ctx_cert:
                client_main.main()
            self.assertEqual(ctx_cert.exception.code, 1)

    def test_command_line_and_receiver_error_and_progress_branches(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_conn = MagicMock()
            fake_conn.connected = True
            fake_conn.request.return_value = {"v": 1, "ok": False, "code": "rate_limited"}
            out = io.StringIO()
            cli = CommandLine(fake_conn, output=out, download_dir=tmp, auto_accept=True)

            # Validation errors in CLI commands
            for bad_cmd in ("/unknown", "/users extra", "/all", "/msg onlyuser", "/file onlypath", "/accept a b"):
                with self.assertRaises(ValueError):
                    cli.execute(bad_cmd)

            cli.execute("   ")
            cli.execute("/all test throttled")
            self.assertIn("rate_limited", out.getvalue())

            # Exercise progress & completion callbacks
            cli._on_progress(
                TransferProgress(
                    transfer_id=str(uuid.uuid4()),
                    filename="a.bin",
                    peer="bob",
                    direction="send",
                    chunks_done=1,
                    total_chunks=2,
                    bytes_done=50,
                    total_bytes=100,
                )
            )
            cli._on_send_complete(str(uuid.uuid4()), True, {})
            cli._on_send_complete(str(uuid.uuid4()), False, {"code": "rejected"})
            cli._on_receive_complete(str(uuid.uuid4()), True, {"filename": "a.bin", "path": "dl/a.bin"})
            cli._on_receive_complete(str(uuid.uuid4()), False, {"code": "checksum_mismatch"})
            rendered = out.getvalue()
            self.assertIn("50.0%", rendered)
            self.assertIn("SHA-256 khớp", rendered)

            # Receiver ambiguous offer & status cleanup branches
            receiver = FileReceiver(lambda *a, **kw: {"ok": True}, download_dir=tmp)
            digest = "a" * 64
            for _ in range(2):
                receiver.handle_event(
                    {
                        "v": 1,
                        "type": MessageType.FILE_OFFER_EVENT,
                        "transfer_id": str(uuid.uuid4()),
                        "from": "alice",
                        "filename": "doc.txt",
                        "size": 0,
                        "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                        "chunk_size": 1024,
                        "total_chunks": 0,
                    }
                )
            with self.assertRaises(TransferError) as amb_ctx:
                receiver.accept()
            self.assertEqual(amb_ctx.exception.code, "ambiguous_transfer")


if __name__ == "__main__":
    unittest.main()
