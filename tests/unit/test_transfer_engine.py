import base64
import hashlib
import io
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from collab.client.commands import CommandLine
from collab.client.discovery import UDPHeartbeat, discover_server
from collab.common.errors import TransferError
from collab.common.protocol import MessageType, make_message
from collab.server.discovery import DiscoveryServer
from collab.server.sessions import Session, SessionRegistry
from collab.server.transfer_coordinator import TransferCoordinator
from collab.transfer.receiver import FileReceiver
from collab.transfer.sender import FileSender


class FakeConnection:
    def __init__(self):
        self.connected = True
        self.requests: list[tuple[str, dict]] = []
        self.responder = None

    def request(self, kind: str, *, timeout: float = 15.0, **fields):
        self.requests.append((kind, fields))
        if self.responder:
            return self.responder(kind, fields)
        return {"v": 1, "type": f"{kind}_result", "ok": True}

    def close(self):
        self.connected = False


class TransferEngineUnitTests(unittest.TestCase):
    def test_coordinator_rejects_self_or_offline_recipient_and_enforces_sequence(self):
        registry = SessionRegistry()
        sent_messages: list[tuple[str, dict]] = []

        def fake_send(session: Session, message: dict) -> None:
            sent_messages.append((session.username, message))

        alice = Session("alice", object(), "127.0.0.1", 50001, str(uuid.uuid4()))
        bob = Session("bob", object(), "127.0.0.1", 50002, str(uuid.uuid4()))
        registry.add(alice)
        registry.add(bob)

        coordinator = TransferCoordinator(
            registry,
            fake_send,
            offer_timeout=5.0,
            chunk_idle_timeout=5.0,
            max_active_per_user=2,
        )
        tid = str(uuid.uuid4())
        payload = b"hello reliable world"
        digest = hashlib.sha256(payload).hexdigest()

        # Offline recipient rejected
        offline_resp = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_OFFER,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                to="charlie",
                filename="greeting.txt",
                size=len(payload),
                sha256=digest,
                chunk_size=1024,
                total_chunks=1,
            ),
        )
        self.assertFalse(offline_resp["ok"])
        self.assertEqual(offline_resp["code"], "recipient_unavailable")

        # Valid offer to bob
        offer_resp = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_OFFER,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                to="bob",
                filename="greeting.txt",
                size=len(payload),
                sha256=digest,
                chunk_size=1024,
                total_chunks=1,
            ),
        )
        self.assertTrue(offer_resp["ok"])
        self.assertEqual(sent_messages[-1][0], "bob")
        self.assertEqual(sent_messages[-1][1]["type"], MessageType.FILE_OFFER_EVENT)

        # Duplicate transfer_id rejected
        dup_resp = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_OFFER,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                to="bob",
                filename="greeting.txt",
                size=len(payload),
                sha256=digest,
                chunk_size=1024,
                total_chunks=1,
            ),
        )
        self.assertFalse(dup_resp["ok"])
        self.assertEqual(dup_resp["code"], "duplicate_transfer")

        # Sending chunk before accept fails
        early_chunk = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_CHUNK,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                index=0,
                data=base64.b64encode(payload).decode("ascii"),
            ),
        )
        self.assertFalse(early_chunk["ok"])
        self.assertEqual(early_chunk["code"], "invalid_transfer_state")

        # Bob accepts
        accept_resp = coordinator.handle_request(
            bob,
            make_message(MessageType.FILE_ACCEPT, request_id=str(uuid.uuid4()), transfer_id=tid),
        )
        self.assertTrue(accept_resp["ok"])
        self.assertEqual(sent_messages[-1][0], "alice")
        self.assertEqual(sent_messages[-1][1]["type"], MessageType.FILE_DECISION)
        self.assertTrue(sent_messages[-1][1]["accepted"])

        # Out-of-order chunk index=1 rejected
        bad_index = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_CHUNK,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                index=1,
                data=base64.b64encode(payload).decode("ascii"),
            ),
        )
        self.assertFalse(bad_index["ok"])
        self.assertEqual(bad_index["code"], "chunk_out_of_order")

        # Invalid Base64 chunk rejected
        bad_b64 = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_CHUNK,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                index=0,
                data="***not-base64***",
            ),
        )
        self.assertFalse(bad_b64["ok"])
        self.assertEqual(bad_b64["code"], "invalid_chunk")

        # Explicit cancel from sender notifies recipient
        cancel_resp = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_CANCEL,
                request_id=str(uuid.uuid4()),
                transfer_id=tid,
                reason="user_cancelled",
            ),
        )
        self.assertTrue(cancel_resp["ok"])
        self.assertEqual(sent_messages[-1][0], "bob")
        self.assertEqual(sent_messages[-1][1]["code"], "transfer_cancelled")

    def test_coordinator_quota_and_invalid_uuid_handling(self):
        registry = SessionRegistry()
        alice = Session("alice", object(), "127.0.0.1", 50001, str(uuid.uuid4()))
        bob = Session("bob", object(), "127.0.0.1", 50002, str(uuid.uuid4()))
        registry.add(alice)
        registry.add(bob)
        coordinator = TransferCoordinator(registry, lambda s, m: None, max_active_per_user=1)

        bad_tid = coordinator.handle_request(
            bob,
            make_message(MessageType.FILE_ACCEPT, request_id=str(uuid.uuid4()), transfer_id="bad"),
        )
        self.assertFalse(bad_tid["ok"])

        digest = hashlib.sha256(b"a").hexdigest()
        first = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_OFFER,
                request_id=str(uuid.uuid4()),
                transfer_id=str(uuid.uuid4()),
                to="bob",
                filename="one.txt",
                size=1,
                sha256=digest,
                chunk_size=1024,
                total_chunks=1,
            ),
        )
        self.assertTrue(first["ok"])
        second = coordinator.handle_request(
            alice,
            make_message(
                MessageType.FILE_OFFER,
                request_id=str(uuid.uuid4()),
                transfer_id=str(uuid.uuid4()),
                to="bob",
                filename="two.txt",
                size=1,
                sha256=digest,
                chunk_size=1024,
                total_chunks=1,
            ),
        )
        self.assertFalse(second["ok"])
        self.assertEqual(second["code"], "too_many_transfers")

    def test_receiver_deletes_part_file_when_checksum_fails_or_stalls(self):
        with tempfile.TemporaryDirectory() as tmp:
            ack_done = threading.Event()
            ack_payloads: list[dict] = []

            def fake_request(kind: str, *, timeout: float = 15.0, **fields):
                if kind == MessageType.FILE_ACK:
                    ack_payloads.append(fields)
                    ack_done.set()
                return {"v": 1, "type": f"{kind}_result", "ok": True}

            receiver = FileReceiver(fake_request, download_dir=tmp, idle_timeout=0.05)
            tid = str(uuid.uuid4())
            good_bytes = b"authentic file content"
            wrong_bytes = b"tampered! file content"
            declared_hash = hashlib.sha256(good_bytes).hexdigest()

            receiver.handle_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_OFFER_EVENT,
                    "transfer_id": tid,
                    "from": "alice",
                    "filename": "secret.txt",
                    "size": len(good_bytes),
                    "sha256": declared_hash,
                    "chunk_size": 1024,
                    "total_chunks": 1,
                    "expires_in_sec": 60,
                }
            )
            receiver.accept(tid[:8])
            receiver.handle_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_CHUNK_EVENT,
                    "transfer_id": tid,
                    "from": "alice",
                    "index": 0,
                    "data": base64.b64encode(wrong_bytes).decode("ascii"),
                }
            )
            receiver.handle_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_END_EVENT,
                    "transfer_id": tid,
                    "from": "alice",
                    "size": len(good_bytes),
                    "sha256": declared_hash,
                    "total_chunks": 1,
                }
            )
            self.assertTrue(ack_done.wait(2.0))
            self.assertFalse(ack_payloads[0]["ok"])
            self.assertEqual(ack_payloads[0]["code"], "checksum_mismatch")
            self.assertEqual(list(Path(tmp).iterdir()), [])

            # Also test stalled receive reap_expired and manual cancel
            tid2 = str(uuid.uuid4())
            receiver.handle_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_OFFER_EVENT,
                    "transfer_id": tid2,
                    "from": "alice",
                    "filename": "stalled.txt",
                    "size": 100,
                    "sha256": declared_hash,
                    "chunk_size": 50,
                    "total_chunks": 2,
                    "expires_in_sec": 60,
                }
            )
            receiver.accept()
            time.sleep(0.08)
            reaped = receiver.reap_expired()
            self.assertIn(tid2, reaped)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_sender_cancel_abort_and_source_modified_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "changing.bin"
            src.write_bytes(b"initial-ten-bytes")

            def fake_request(kind: str, *, timeout: float = 15.0, **fields):
                return {"v": 1, "type": f"{kind}_result", "ok": True}

            sender = FileSender(fake_request, offer_timeout=5.0)
            m1 = sender.start_send(src, "bob")
            cancelled_id = sender.cancel(m1.transfer_id[:8])
            self.assertEqual(cancelled_id, m1.transfer_id)
            out1 = sender.wait(m1.transfer_id, timeout=2.0)
            self.assertFalse(out1["ok"])
            self.assertEqual(out1["code"], "cancelled")

            # Mutate file on disk after offer before accept arrives
            m2 = sender.start_send(src, "bob")
            src.write_bytes(b"short")
            sender.handle_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_DECISION,
                    "transfer_id": m2.transfer_id,
                    "accepted": True,
                    "by": "bob",
                }
            )
            out2 = sender.wait(m2.transfer_id, timeout=2.0)
            self.assertFalse(out2["ok"])
            self.assertEqual(out2["code"], "source_modified")

    def test_cli_full_command_set_and_event_rendering(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "note.txt"
            sample.write_text("hello cli", encoding="utf-8")
            dl_dir = Path(tmp) / "dl"

            conn = FakeConnection()
            out = io.StringIO()
            commands_iter = iter(
                [
                    "/help",
                    "/users",
                    "/all xin chao ca nha",
                    "/msg bob chao ban",
                    f'/file "{sample.as_posix()}" bob',
                    "/cancel",
                    "/quit",
                ]
            )
            cli = CommandLine(
                conn,
                output=out,
                input_fn=lambda prompt="": next(commands_iter),
                download_dir=dl_dir,
            )

            # Exercise event rendering for user_list, presence, chat, file offer, reject
            cli.show_event(
                {
                    "type": "user_list",
                    "users": [{"username": "alice", "host": "127.0.0.1", "port": 40001}],
                }
            )
            cli.show_event({"type": "presence_online", "username": "bob"})
            cli.show_event({"type": "chat_message", "from": "bob", "to": "alice", "text": "hi"})
            cli.show_event({"type": "presence_offline", "username": "bob"})

            tid = str(uuid.uuid4())
            cli.show_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_OFFER_EVENT,
                    "transfer_id": tid,
                    "from": "bob",
                    "filename": "demo.txt",
                    "size": 12,
                    "sha256": hashlib.sha256(b"hello world!").hexdigest(),
                    "chunk_size": 1024,
                    "total_chunks": 1,
                    "expires_in_sec": 60,
                }
            )
            cli.execute(f"/reject {tid[:8]}")
            with patch("getpass.getpass", return_value="password123"):
                cli.execute("/register alice")
                cli.execute("/login alice")

            cli.run()
            rendered = out.getvalue()
            self.assertIn("[online]", rendered)
            self.assertIn("tin nhắn riêng", rendered)
            self.assertIn("Đã từ chối", rendered)
            self.assertIn("Đăng nhập thành công", rendered)

            # Verify connection_lost stops CLI cleanly
            cli.running = True
            cli.show_event({"type": "connection_lost", "reason": "test drop"})
            self.assertFalse(cli.running)

    def test_cli_logout_aborts_local_transfers_and_reports_error_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample = Path(tmp) / "outgoing.bin"
            sample.write_bytes(b"payload-before-logout")
            dl_dir = Path(tmp) / "downloads"

            conn = FakeConnection()
            out = io.StringIO()
            cli = CommandLine(conn, output=out, download_dir=dl_dir)
            cli.users = [{"username": "alice", "host": "127.0.0.1", "port": 40001}]
            try:
                # Start an outgoing offer and accept an incoming offer (.part file open on disk)
                outgoing_manifest = cli.file_sender.start_send(sample, "bob")
                incoming_tid = str(uuid.uuid4())
                cli.show_event(
                    {
                        "v": 1,
                        "type": MessageType.FILE_OFFER_EVENT,
                        "transfer_id": incoming_tid,
                        "from": "bob",
                        "filename": "incoming.bin",
                        "size": 64,
                        "sha256": hashlib.sha256(b"x" * 64).hexdigest(),
                        "chunk_size": 64,
                        "total_chunks": 1,
                        "expires_in_sec": 60,
                    }
                )
                cli.execute(f"/accept {incoming_tid[:8]}")
                self.assertEqual(len(list(dl_dir.glob("*.part"))), 1)

                # Successful /logout must abort outgoing worker, remove .part file, and clear users
                cli.execute("/logout")
                sender_outcome = cli.file_sender.wait(outgoing_manifest.transfer_id, timeout=0.4)
                self.assertFalse(sender_outcome["ok"])
                self.assertEqual(sender_outcome["code"], "logged_out")
                self.assertEqual(list(dl_dir.glob("*.part")), [])
                self.assertEqual(cli.users, [])
                self.assertIn("Đã đăng xuất thành công.", out.getvalue())

                # Unauthenticated /logout must surface server error code cleanly
                conn.responder = lambda kind, fields: {
                    "v": 1,
                    "type": "error",
                    "ok": False,
                    "code": "unauthorized",
                }
                out.truncate(0)
                out.seek(0)
                cli.execute("/logout")
                self.assertIn("Đăng xuất thất bại: unauthorized", out.getvalue())
            finally:
                cli.file_sender.abort_all("test_cleanup")
                cli.file_receiver.abort_all("test_cleanup")

    def test_client_udp_discover_and_heartbeat_round_trip(self):
        server = DiscoveryServer(37021, bind_host="127.0.0.1", udp_port=0)
        server.start()
        try:
            assert server._socket is not None
            _, udp_port = server._socket.getsockname()
            found = discover_server(udp_port=udp_port, target_host="127.0.0.1", timeout=0.5, attempts=1)
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found["tcp_port"], 37021)

            hb = UDPHeartbeat("127.0.0.1", udp_port, interval=0.05)
            hb.start()
            time.sleep(0.12)
            hb.stop()
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
