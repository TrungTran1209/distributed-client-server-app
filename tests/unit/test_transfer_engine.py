import base64
import hashlib
import io
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from collab.client.commands import CommandLine
from collab.common.protocol import MessageType, make_message
from collab.server.sessions import Session, SessionRegistry
from collab.server.transfer_coordinator import TransferCoordinator
from collab.transfer.receiver import FileReceiver


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

        coordinator = TransferCoordinator(registry, fake_send, offer_timeout=5.0, chunk_idle_timeout=5.0)
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

    def test_receiver_deletes_part_file_when_checksum_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            ack_done = threading.Event()
            ack_payloads: list[dict] = []

            def fake_request(kind: str, *, timeout: float = 15.0, **fields):
                if kind == MessageType.FILE_ACK:
                    ack_payloads.append(fields)
                    ack_done.set()
                return {"v": 1, "type": f"{kind}_result", "ok": True}

            receiver = FileReceiver(fake_request, download_dir=tmp)
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

    def test_cli_accept_and_reject_commands_use_prefix_matching(self):
        with tempfile.TemporaryDirectory() as tmp:
            conn = FakeConnection()
            out = io.StringIO()
            cli = CommandLine(conn, output=out, download_dir=tmp)
            tid = str(uuid.uuid4())
            cli.show_event(
                {
                    "v": 1,
                    "type": MessageType.FILE_OFFER_EVENT,
                    "transfer_id": tid,
                    "from": "alice",
                    "filename": "demo.txt",
                    "size": 12,
                    "sha256": hashlib.sha256(b"hello world!").hexdigest(),
                    "chunk_size": 1024,
                    "total_chunks": 1,
                    "expires_in_sec": 60,
                }
            )
            self.assertIn(tid[:8], out.getvalue())
            cli.execute(f"/reject {tid[:8]}")
            self.assertEqual(conn.requests[-1][0], MessageType.FILE_REJECT)
            self.assertEqual(conn.requests[-1][1]["transfer_id"], tid)


if __name__ == "__main__":
    unittest.main()
