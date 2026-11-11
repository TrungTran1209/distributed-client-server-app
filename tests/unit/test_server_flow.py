import socket
import tempfile
import threading
import time
import unicodedata
import unittest
import uuid
from pathlib import Path

from collab.client.connection import ClientConnection
from collab.common.framing import encode_frame, recv_frame
from collab.common.protocol import decode_message, encode_message, make_message
from collab.server.auth import AuthService
from collab.server.server import CollaborationServer
from collab.server.user_store import UserStore


class PassthroughTLSContext:
    """Keeps this focused socketpair test independent of certificate fixtures."""

    @staticmethod
    def wrap_socket(sock, *, server_side=False, server_hostname=None):
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

    def test_logout_removes_session_and_broadcasts_offline_presence(self):
        alice = self.connect()
        bob = self.connect()
        self.register_and_login(alice, "alice")
        self.register_and_login(bob, "bob")
        self.receive(alice)  # bob's presence_online event

        self.send(alice, "logout")

        result = self.receive(alice)
        self.assertEqual(result["type"], "logout_result")
        self.assertTrue(result["ok"])
        offline = self.receive(bob)
        self.assertEqual(offline["type"], "presence_offline")
        self.assertEqual(offline["username"], "alice")

        self.send(alice, "chat_send", to=None, text="should be rejected")
        rejected = self.receive(alice)
        self.assertEqual(rejected["type"], "error")
        self.assertEqual(rejected["code"], "unauthorized")

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

    def test_silent_unauthenticated_client_closed_within_auth_timeout(self):
        fast_auth_server = CollaborationServer(
            "127.0.0.1",
            0,
            PassthroughTLSContext(),
            AuthService(UserStore(Path(self.temp.name) / "auth_timeout.sqlite3")),
            idle_timeout=5,
            auth_timeout=0.25,
        )
        server_sock, client_sock = socket.socketpair()
        client_sock.settimeout(1.5)
        self.peers.append(client_sock)
        started = time.monotonic()
        worker = threading.Thread(
            target=fast_auth_server._handle_connection,
            args=(server_sock, ("127.0.0.1", 41001)),
            daemon=True,
        )
        worker.start()
        self.workers.append(worker)
        # Greet with hello, then stay silent without logging in
        self.send(client_sock, "hello")
        self.assertEqual(self.receive(client_sock)["type"], "welcome")
        worker.join(timeout=1.0)
        elapsed = time.monotonic() - started
        self.assertFalse(worker.is_alive(), "unauthenticated worker stayed alive past auth_timeout")
        self.assertLess(elapsed, 1.0)

    def test_rate_limits_login_failures_registrations_and_chat_burst(self):
        limited_server = CollaborationServer(
            "127.0.0.1",
            0,
            PassthroughTLSContext(),
            AuthService(UserStore(Path(self.temp.name) / "ratelimit.sqlite3")),
            max_auth_failures=3,
            register_limit_per_ip=2,
            chat_rate=1.0,
            chat_burst=2,
        )

        def connect_limited(ip: str = "127.0.0.1", port: int = 42000):
            s_sock, c_sock = socket.socketpair()
            c_sock.settimeout(2)
            self.peers.append(c_sock)
            w = threading.Thread(
                target=limited_server._handle_connection,
                args=(s_sock, (ip, port)),
                daemon=True,
            )
            w.start()
            self.workers.append(w)
            self.send(c_sock, "hello")
            self.assertEqual(self.receive(c_sock)["type"], "welcome")
            return c_sock, w

        # 1. Per-IP registration rate limit (2 allowed, 3rd throttled with rate_limited)
        reg_sock, _ = connect_limited("10.0.0.5", 42001)
        self.send(reg_sock, "register", username="u1", password="password123")
        self.assertTrue(self.receive(reg_sock)["ok"])
        self.send(reg_sock, "register", username="u2", password="password123")
        self.assertTrue(self.receive(reg_sock)["ok"])
        self.send(reg_sock, "register", username="u3", password="password123")
        reg_throttled = self.receive(reg_sock)
        self.assertFalse(reg_throttled["ok"])
        self.assertEqual(reg_throttled["code"], "rate_limited")

        # 2. Per-connection login failure cap closes connection on 3rd failure
        bad_sock, bad_worker = connect_limited("10.0.0.6", 42002)
        for attempt in range(1, 4):
            self.send(bad_sock, "login", username="u1", password="wrong-password")
            resp = self.receive(bad_sock)
            self.assertFalse(resp["ok"])
            if attempt == 3:
                self.assertEqual(resp["code"], "rate_limited")
        bad_worker.join(timeout=1.0)
        self.assertFalse(bad_worker.is_alive())

        # 3. Per-session chat token bucket (burst=2 allowed, 3rd immediate chat rate_limited)
        chat_sock, _ = connect_limited("10.0.0.7", 42003)
        self.send(chat_sock, "login", username="u1", password="password123")
        self.assertTrue(self.receive(chat_sock)["ok"])
        self.assertEqual(self.receive(chat_sock)["type"], "user_list")
        self.send(chat_sock, "chat_send", to=None, text="msg 1")
        self.assertTrue(self.receive(chat_sock)["ok"])
        self.send(chat_sock, "chat_send", to=None, text="msg 2")
        self.assertTrue(self.receive(chat_sock)["ok"])
        self.send(chat_sock, "chat_send", to=None, text="msg 3")
        chat_throttled = self.receive(chat_sock)
        self.assertFalse(chat_throttled["ok"])
        self.assertEqual(chat_throttled["code"], "rate_limited")

    def test_stalled_peer_send_times_out_and_closes_socket(self):
        server = CollaborationServer(
            "127.0.0.1",
            0,
            PassthroughTLSContext(),
            AuthService(UserStore(Path(self.temp.name) / "send_timeout.sqlite3")),
            send_timeout=0.15,
        )

        class StalledSocket:
            def __init__(self):
                self.closed = threading.Event()

            def sendall(self, data: bytes) -> None:
                if not self.closed.wait(2.0):
                    raise AssertionError("stalled socket was never closed by send_timeout")
                raise OSError("socket closed due to send timeout")

            def shutdown(self, how: int) -> None:
                self.closed.set()

            def close(self) -> None:
                self.closed.set()

        from collab.server.sessions import Session

        stalled = StalledSocket()
        sess = Session("stalled_user", stalled, "127.0.0.1", 43001, str(uuid.uuid4()))
        server.sessions.add(sess)

        reaper_done = threading.Event()

        def run_reaper():
            deadline = time.monotonic() + 1.5
            while not stalled.closed.is_set() and time.monotonic() < deadline:
                server._reap_idle_sessions()
                time.sleep(0.03)
            reaper_done.set()

        t = threading.Thread(target=run_reaper, daemon=True)
        t.start()
        started = time.monotonic()
        server._send(sess, make_message("presence_online", username="alice"))
        elapsed = time.monotonic() - started
        reaper_done.wait(1.0)
        self.assertTrue(stalled.closed.is_set())
        self.assertLess(elapsed, 1.0)

    def test_direct_chat_normalizes_unicode_recipient_and_auth_nfkc_password_backcompat(self):
        store = UserStore(Path(self.temp.name) / "unicode.sqlite3")
        auth = AuthService(store)
        # Legacy account created directly in UserStore with NFD password before NFKC policy
        legacy_nfd_pw = unicodedata.normalize("NFD", "mật_khẩu_cũ_123")
        store.create_user("legacy", legacy_nfd_pw)
        ok_legacy, _ = auth.login("legacy", legacy_nfd_pw)
        self.assertTrue(ok_legacy)

        # New account registered via AuthService normalizes password with NFKC
        nfd_pw = unicodedata.normalize("NFD", "mật_khẩu_mới_123")
        nfc_pw = unicodedata.normalize("NFC", "mật_khẩu_mới_123")
        ok_reg, _ = auth.register("phú", nfd_pw)
        self.assertTrue(ok_reg)
        ok_login, _ = auth.login("phú", nfc_pw)
        self.assertTrue(ok_login)

        # Direct chat with NFD `to` reaches NFC session "phú"
        alice = self.connect()
        phu = self.connect()
        self.register_and_login(alice, "alice")
        self.register_and_login(phu, unicodedata.normalize("NFC", "phú"))
        self.assertEqual(self.receive(alice)["type"], "presence_online")

        nfd_target = unicodedata.normalize("NFD", "phú")
        self.send(alice, "chat_send", to=nfd_target, text="Xin chào Phú")
        incoming = self.receive(phu)
        result = self.receive(alice)
        self.assertTrue(result["ok"])
        self.assertEqual(incoming["text"], "Xin chào Phú")

    def test_client_connection_graceful_close_suppresses_connection_lost_event(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        host, port = listener.getsockname()
        events: list[dict] = []

        def accept_one():
            raw, addr = listener.accept()
            listener.close()
            self.server._handle_connection(raw, addr)

        t = threading.Thread(target=accept_one, daemon=True)
        t.start()
        self.workers.append(t)

        conn = ClientConnection(
            host,
            port,
            PassthroughTLSContext(),
            on_event=events.append,
        )
        conn.connect()
        conn.close()
        connection_lost_events = [e for e in events if e.get("type") == "connection_lost"]
        self.assertEqual(connection_lost_events, [])


if __name__ == "__main__":
    unittest.main()
