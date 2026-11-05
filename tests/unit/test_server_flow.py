import socket
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import decode_message, encode_message, make_message
from collab.server.auth import AuthService
from collab.server.server import CollaborationServer
from collab.server.user_store import UserStore


class PassthroughTLSContext:
    """Keeps this focused socketpair test independent of certificate fixtures."""

    @staticmethod
    def wrap_socket(sock, *, server_side):
        return sock


class ServerFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.server = CollaborationServer(
            "127.0.0.1", 0, PassthroughTLSContext(),
            AuthService(UserStore(Path(self.temp.name) / "users.sqlite3")),
        )
        self.peers = []
        self.workers = []

    def tearDown(self):
        for peer in self.peers:
            peer.close()
        for worker in self.workers:
            worker.join(timeout=2)
        self.temp.cleanup()

    def connect(self):
        server_sock, client_sock = socket.socketpair()
        client_sock.settimeout(2)
        self.peers.append(client_sock)
        worker = threading.Thread(
            target=self.server._handle_connection,
            args=(server_sock, ("127.0.0.1", 40000 + len(self.peers))),
            daemon=True,
        )
        worker.start()
        self.workers.append(worker)
        self.send(client_sock, "hello")
        self.assertEqual(self.receive(client_sock)["type"], "welcome")
        return client_sock

    @staticmethod
    def send(sock, kind, **fields):
        message = make_message(kind, request_id=str(uuid.uuid4()), **fields)
        sock.sendall(encode_frame(encode_message(message)))

    @staticmethod
    def receive(sock):
        return decode_message(recv_frame(sock))

    def register_and_login(self, sock, username):
        self.send(sock, "register", username=username, password="correct horse battery")
        self.assertTrue(self.receive(sock)["ok"])
        self.send(sock, "login", username=username, password="correct horse battery")
        self.assertTrue(self.receive(sock)["ok"])
        self.assertEqual(self.receive(sock)["type"], "user_list")

    def test_hello_login_and_direct_chat(self):
        alice = self.connect()
        bob = self.connect()
        self.register_and_login(alice, "alice")
        self.register_and_login(bob, "bob")
        self.assertEqual(self.receive(alice)["type"], "presence_online")

        self.send(alice, "chat_send", to="bob", text="hello Bob")
        incoming = self.receive(bob)
        result = self.receive(alice)
        self.assertEqual(incoming["type"], "chat_message")
        self.assertEqual(incoming["text"], "hello Bob")
        self.assertTrue(result["ok"])

    def test_broadcast_chat(self):
        alice = self.connect()
        bob = self.connect()
        self.register_and_login(alice, "alice")
        self.register_and_login(bob, "bob")
        self.receive(alice)  # bob's presence_online event

        self.send(alice, "chat_send", to=None, text="hello everyone")
        self.assertEqual(self.receive(bob)["text"], "hello everyone")
        self.assertTrue(self.receive(alice)["ok"])

    def test_shutdown_unblocks_accept_loop(self):
        worker = threading.Thread(target=self.server.serve_forever, daemon=True)
        worker.start()
        deadline = time.monotonic() + 2
        while self.server._listener is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(self.server._listener)
        self.server.shutdown()
        worker.join(timeout=2)
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
