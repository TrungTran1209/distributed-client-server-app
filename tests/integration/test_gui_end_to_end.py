"""End-to-end GUI-controller test over real TLS: host, two clients, chat, chunked file transfer."""
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from collab.common.tls import create_client_context
from collab.gui.controllers.client_controller import ClientController
from collab.gui.controllers.server_controller import ServerController
from collab.gui.widgets.cert_gen_dialog import generate_self_signed

_app = QApplication.instance() or QApplication(sys.argv[:1])


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class GuiEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cert, key = generate_self_signed(root / "certs", "localhost", ["127.0.0.1"], ["localhost"])
        self.server = ServerController()
        started = []
        self.server.server_started.connect(lambda: started.append(1))
        self.server.start_server({
            "host": "127.0.0.1", "port": 0, "udp_port": 0, "cert": self.cert, "key": key,
            "database": str(root / "users.sqlite3"), "idle_timeout": 90, "auth_timeout": 60,
        })
        self.assertTrue(wait_for(lambda: started), "server did not start")
        self.port = self.server.tcp_port
        self.clients = []

    def tearDown(self):
        for client in self.clients:
            client.shutdown_blocking()
        self.server.stop_server()
        self.tmp.cleanup()

    def _client(self, name, *, auto_accept=True):
        client = ClientController(auto_accept=auto_accept)
        client.inbox, client.files, client.done, client.offers, client.errors = [], [], [], [], []
        client.message_received.connect(client.inbox.append)
        client.transfer_done.connect(lambda tid, ok, d, c=client: c.done.append((tid, ok, d)))
        client.transfer_offer.connect(client.offers.append)
        client.transfer_error.connect(client.errors.append)
        dl = Path(self.tmp.name) / f"dl-{name}"
        dl.mkdir()
        connected, regs, auth = [], [], []
        client.connected.connect(connected.append)
        client.register_finished.connect(lambda ok, m: regs.append((ok, m)))
        client.auth_succeeded.connect(auth.append)
        client.connect_to_server("127.0.0.1", self.port, create_client_context(self.cert), str(dl), udp_port=None)
        self.assertTrue(wait_for(lambda: connected), "connect failed")
        client.register(name, "password-123")
        self.assertTrue(wait_for(lambda: regs))
        self.assertTrue(regs[0][0], regs[0][1])
        client.login(name, "password-123")
        self.assertTrue(wait_for(lambda: auth), "login failed")
        client.dl = dl
        self.clients.append(client)
        return client

    def test_login_failure_reports_message(self):
        client = ClientController()
        ok, bad = [], []
        client.connected.connect(ok.append)
        client.auth_failed.connect(bad.append)
        client.connect_to_server("127.0.0.1", self.port, create_client_context(self.cert), self.tmp.name, udp_port=None)
        self.assertTrue(wait_for(lambda: ok))
        client.login("nobody", "wrong-password")
        self.assertTrue(wait_for(lambda: bad))
        self.assertIn("Sai", bad[0])
        client.shutdown_blocking()

    def test_untrusted_certificate_is_rejected_with_actionable_message(self):
        client = ClientController()
        lost = []
        client.connection_lost.connect(lost.append)
        import ssl
        client.connect_to_server("127.0.0.1", self.port, ssl.create_default_context(), self.tmp.name, udp_port=None)
        self.assertTrue(wait_for(lambda: lost))
        self.assertIn("chứng chỉ", lost[0].lower())

    def test_chat_and_chunked_file_transfer(self):
        alice, bob = self._client("alice"), self._client("bob")
        self.assertTrue(wait_for(lambda: {u["username"] for u in alice.get_users()} >= {"alice", "bob"}))

        alice.send_chat(None, "hello everyone")
        self.assertTrue(wait_for(lambda: bob.inbox))
        self.assertEqual(bob.inbox[0]["text"], "hello everyone")
        alice.send_chat("bob", "psst")
        self.assertTrue(wait_for(lambda: len(bob.inbox) == 2))
        self.assertEqual(bob.inbox[1]["to"], "bob")

        payload = os.urandom(200_000)  # > 3 chunks of 64 KiB
        src = Path(self.tmp.name) / "blob.bin"
        src.write_bytes(payload)
        alice.send_file(str(src), "bob")
        self.assertTrue(wait_for(lambda: bob.offers), "no offer received")
        self.assertEqual(bob.offers[0]["total_chunks"], 4)
        bob.accept_file(bob.offers[0]["transfer_id"])
        self.assertTrue(wait_for(lambda: alice.done and bob.done, 20), "transfer did not complete")
        self.assertTrue(alice.done[0][1] and bob.done[0][1])
        out = Path(bob.done[0][2]["path"])
        self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(), hashlib.sha256(payload).hexdigest())
        self.assertEqual(list(bob.dl.glob("*.part")), [])

    def test_reject_reports_to_sender_and_leaves_no_files(self):
        alice, bob = self._client("alice"), self._client("bob", auto_accept=False)
        self.assertTrue(wait_for(lambda: {u["username"] for u in alice.get_users()} >= {"alice", "bob"}))
        src = Path(self.tmp.name) / "r.bin"
        src.write_bytes(b"x" * 1000)
        alice.send_file(str(src), "bob")
        self.assertTrue(wait_for(lambda: bob.offers))
        bob.reject_file(bob.offers[0]["transfer_id"])
        self.assertTrue(wait_for(lambda: alice.done))
        self.assertFalse(alice.done[0][1])
        self.assertEqual(alice.done[0][2].get("code"), "rejected")
        self.assertEqual(list(bob.dl.iterdir()), [])

    def test_server_stop_notifies_clients_and_port_is_released(self):
        alice = self._client("alice")
        lost = []
        alice.connection_lost.connect(lost.append)
        self.server.stop_server()
        self.assertTrue(wait_for(lambda: lost), "client was not told the connection dropped")
        self.assertFalse(alice.is_connected())
        self.assertFalse(self.server.is_running())


if __name__ == "__main__":
    unittest.main()
