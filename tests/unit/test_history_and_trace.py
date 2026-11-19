"""Unit tests for UserStore directory, SQLite MessageStore, offline chat, chat_history, and chunk tracing."""

from __future__ import annotations

import base64
import hashlib
import socket
import tempfile
import threading
import unittest
import uuid
from pathlib import Path

from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import MessageType, decode_message, encode_message, make_message
from collab.server.auth import AuthService
from collab.server.message_store import MessageStore
from collab.server.server import CollaborationServer
from collab.server.user_store import UserStore


class _PassthroughTLS:
    @staticmethod
    def wrap_socket(sock, *, server_side=False, server_hostname=None):
        return sock


class MessageStoreAndDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "app.sqlite3"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_user_store_lists_registered_usernames_and_checks_existence(self) -> None:
        users = UserStore(self.db_path)
        self.assertEqual(users.list_usernames(), [])
        self.assertFalse(users.user_exists("alice"))

        users.create_user("bob", "password-123")
        users.create_user("alice", "password-123")
        self.assertEqual(users.list_usernames(), ["alice", "bob"])
        self.assertTrue(users.user_exists("alice"))
        self.assertTrue(users.user_exists("bob"))
        self.assertFalse(users.user_exists("charlie"))

    def test_message_store_isolates_private_messages_and_preserves_order(self) -> None:
        store = MessageStore(self.db_path)
        self.assertEqual(store.count_messages(), 0)

        store.save_message("m1", "alice", None, "Chào cả nhóm", "2026-11-19T01:00:00Z")
        store.save_message("m2", "alice", "bob", "Tin riêng cho Bob", "2026-11-19T01:00:01Z")
        store.save_message("m3", "alice", "carol", "Bí mật với Carol", "2026-11-19T01:00:02Z")
        store.save_message("m4", "bob", "alice", "Bob trả lời Alice", "2026-11-19T01:00:03Z")

        self.assertEqual(store.count_messages(), 4)

        bob_history = store.get_history_for_user("bob", limit=50)
        self.assertEqual([m["message_id"] for m in bob_history], ["m1", "m2", "m4"])
        self.assertTrue(all(m["text"] != "Bí mật với Carol" for m in bob_history))

        carol_history = store.get_history_for_user("carol", limit=50)
        self.assertEqual([m["message_id"] for m in carol_history], ["m1", "m3"])


class OfflineChatHistoryAndTraceServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "server.sqlite3"
        self.traces: list[dict] = []
        users = UserStore(self.db_path)
        messages = MessageStore(self.db_path)
        self.server = CollaborationServer(
            "127.0.0.1",
            0,
            _PassthroughTLS(),
            AuthService(users),
            message_store=messages,
            on_trace=self.traces.append,
        )
        self.socks: list[socket.socket] = []
        self.workers: list[threading.Thread] = []

    def tearDown(self) -> None:
        for sock in self.socks:
            try:
                sock.close()
            except OSError:
                pass
        for w in self.workers:
            w.join(timeout=2)
        self.tmp.cleanup()

    def _connect(self) -> socket.socket:
        s_sock, c_sock = socket.socketpair()
        c_sock.settimeout(3.0)
        self.socks.append(c_sock)
        worker = threading.Thread(
            target=self.server._handle_connection,
            args=(s_sock, ("127.0.0.1", 45000 + len(self.socks))),
            daemon=True,
        )
        worker.start()
        self.workers.append(worker)
        self._send(c_sock, MessageType.HELLO)
        self.assertEqual(self._recv(c_sock)["type"], MessageType.WELCOME)
        return c_sock

    @staticmethod
    def _send(sock: socket.socket, kind: str, **fields) -> str:
        req_id = str(uuid.uuid4())
        msg = make_message(kind, request_id=req_id, **fields)
        sock.sendall(encode_frame(encode_message(msg)))
        return req_id

    @staticmethod
    def _recv(sock: socket.socket) -> dict:
        return decode_message(recv_frame(sock))

    def test_directory_offline_chat_and_history_restoration(self) -> None:
        # Bob registers first, then disconnects without staying online
        bob_reg = self._connect()
        self._send(bob_reg, MessageType.REGISTER, username="bob", password="secret-password-99")
        self.assertTrue(self._recv(bob_reg)["ok"])
        bob_reg.close()

        # Alice registers and logs in while Bob is offline
        alice = self._connect()
        self._send(alice, MessageType.REGISTER, username="alice", password="secret-password-99")
        self.assertTrue(self._recv(alice)["ok"])
        self._send(alice, MessageType.LOGIN, username="alice", password="secret-password-99")
        self.assertTrue(self._recv(alice)["ok"])

        ulist = self._recv(alice)
        self.assertEqual(ulist["type"], MessageType.USER_LIST)
        # Backward-compat: `users` only lists online users
        self.assertEqual([u["username"] for u in ulist["users"]], ["alice"])
        # New `directory` lists both online & offline registered accounts
        by_name = {u["username"]: u["online"] for u in ulist["directory"]}
        self.assertEqual(by_name, {"alice": True, "bob": False})

        # Alice chats to offline Bob -> succeeds with queued_offline=True
        self._send(alice, MessageType.CHAT_SEND, to="bob", text="Bob ơi khi nào online đọc nhé!")
        chat_res = self._recv(alice)
        self.assertTrue(chat_res["ok"])
        self.assertTrue(chat_res.get("queued_offline"))

        # Alice chats to nonexistent user -> still rejected with recipient_unavailable
        self._send(alice, MessageType.CHAT_SEND, to="ghost_user", text="Ai đó?")
        ghost_res = self._recv(alice)
        self.assertFalse(ghost_res["ok"])
        self.assertEqual(ghost_res["code"], "recipient_unavailable")

        # Broadcast message also saved to history
        self._send(alice, MessageType.CHAT_SEND, to=None, text="Thông báo chung")
        self.assertTrue(self._recv(alice)["ok"])

        # Carol registers while Alice is online -> Alice queries user_directory and sees carol (offline)
        carol = self._connect()
        self._send(carol, MessageType.REGISTER, username="carol", password="secret-password-99")
        self.assertTrue(self._recv(carol)["ok"])
        self._send(alice, MessageType.USER_DIRECTORY)
        refreshed = self._recv(alice)
        self.assertEqual(refreshed["type"], MessageType.USER_DIRECTORY_RESULT)
        self.assertIn("carol", {u["username"] for u in refreshed["directory"]})

        # Now Bob comes online and fetches chat_history -> sees both broadcast and offline DM!
        bob = self._connect()
        self._send(bob, MessageType.LOGIN, username="bob", password="secret-password-99")
        self.assertTrue(self._recv(bob)["ok"])
        bob_ulist = self._recv(bob)
        self.assertEqual(bob_ulist["type"], MessageType.USER_LIST)
        self.assertEqual(self._recv(alice)["type"], MessageType.PRESENCE_ONLINE)

        self._send(bob, MessageType.CHAT_HISTORY, limit=100)
        hist = self._recv(bob)
        self.assertEqual(hist["type"], MessageType.CHAT_HISTORY_RESULT)
        self.assertTrue(hist["ok"])
        texts = [m["text"] for m in hist["messages"]]
        self.assertEqual(texts, ["Bob ơi khi nào online đọc nhé!", "Thông báo chung"])

    def test_server_traces_chunks_and_operations_without_leaking_passwords(self) -> None:
        secret = "ultra-secret-pass-123"
        alice = self._connect()
        bob = self._connect()

        for sock, name in ((alice, "alice"), (bob, "bob")):
            self._send(sock, MessageType.REGISTER, username=name, password=secret)
            self.assertTrue(self._recv(sock)["ok"])
            self._send(sock, MessageType.LOGIN, username=name, password=secret)
            self.assertTrue(self._recv(sock)["ok"])
            self._recv(sock)  # user_list

        self._recv(alice)  # bob presence_online

        payload = b"hello-chunk-trace-world"
        sha = hashlib.sha256(payload).hexdigest()
        tid = str(uuid.uuid4())

        self._send(
            alice,
            MessageType.FILE_OFFER,
            to="bob",
            transfer_id=tid,
            filename="demo.bin",
            size=len(payload),
            sha256=sha,
            chunk_size=65536,
            total_chunks=1,
        )
        self.assertEqual(self._recv(bob)["type"], MessageType.FILE_OFFER_EVENT)
        self.assertTrue(self._recv(alice)["ok"])

        self._send(bob, MessageType.FILE_ACCEPT, transfer_id=tid)
        self.assertEqual(self._recv(alice)["type"], MessageType.FILE_DECISION)
        self.assertTrue(self._recv(bob)["ok"])

        self._send(
            alice,
            MessageType.FILE_CHUNK,
            transfer_id=tid,
            index=0,
            data=base64.b64encode(payload).decode("ascii"),
        )
        self.assertEqual(self._recv(bob)["type"], MessageType.FILE_CHUNK_EVENT)
        self.assertTrue(self._recv(alice)["ok"])

        self._send(alice, MessageType.FILE_END, transfer_id=tid, size=len(payload), sha256=sha)
        self.assertEqual(self._recv(bob)["type"], MessageType.FILE_END_EVENT)
        self.assertTrue(self._recv(alice)["ok"])

        self._send(bob, MessageType.FILE_ACK, transfer_id=tid, ok=True, sha256=sha)
        self.assertEqual(self._recv(alice)["type"], MessageType.FILE_STATUS)
        self.assertTrue(self._recv(bob)["ok"])

        actions = [t["action"] for t in self.traces]
        self.assertIn("register", actions)
        self.assertIn("login", actions)
        self.assertIn("file_offer", actions)
        self.assertIn("file_accept", actions)
        self.assertIn("file_chunk", actions)
        self.assertIn("file_end", actions)
        self.assertIn("file_ack", actions)

        chunk_traces = [t for t in self.traces if t["action"] == "file_chunk"]
        self.assertEqual(len(chunk_traces), 1)
        self.assertEqual(chunk_traces[0]["chunk_index"], 0)
        self.assertEqual(chunk_traces[0]["total_chunks"], 1)
        self.assertEqual(chunk_traces[0]["chunk_bytes"], len(payload))

        # Security invariant: password must NEVER appear anywhere in trace events
        serialized = repr(self.traces)
        self.assertNotIn(secret, serialized)
        self.assertNotIn(payload.decode("utf-8"), serialized)
        self.assertNotIn("raw_payload_preview", serialized)


if __name__ == "__main__":
    unittest.main()
