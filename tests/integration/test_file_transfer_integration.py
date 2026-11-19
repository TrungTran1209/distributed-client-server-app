import hashlib
import os
import shutil
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

from collab.client.connection import ClientConnection
from collab.common.tls import create_client_context, create_server_context
from collab.server.auth import AuthService
from collab.server.server import CollaborationServer
from collab.server.user_store import UserStore
from collab.transfer.receiver import FileReceiver
from collab.transfer.sender import FileSender


def _find_openssl() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    candidates = [
        r"C:\Program Files\Git\usr\bin\openssl.exe",
        r"C:\Program Files\Git\mingw64\bin\openssl.exe",
        r"C:\Program Files (x86)\Git\usr\bin\openssl.exe",
    ]
    for path in candidates:
        if Path(path).is_file():
            return path
    raise RuntimeError("OpenSSL executable not found for integration test certificate generation")


def _generate_self_signed_cert(directory: Path, common_name: str = "localhost") -> tuple[Path, Path]:
    try:
        from collab.gui.widgets.cert_gen_dialog import generate_self_signed
        sub = directory / common_name
        c, k = generate_self_signed(sub, common_name, ["127.0.0.1"], [common_name, "localhost"])
        target_c = directory / f"{common_name}.crt"
        target_k = directory / f"{common_name}.key"
        shutil.copyfile(c, target_c)
        shutil.copyfile(k, target_k)
        return target_c, target_k
    except Exception:
        pass
    cert_path = directory / f"{common_name}.crt"
    key_path = directory / f"{common_name}.key"
    subprocess.run(
        [
            _find_openssl(),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "2",
            "-keyout",
            str(key_path),
            "-out",
            str(cert_path),
            "-subj",
            f"/CN={common_name}",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return cert_path, key_path


class FileTransferTLSIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._cert_dir = tempfile.TemporaryDirectory()
        cert_dir_path = Path(cls._cert_dir.name)
        cls.server_cert, cls.server_key = _generate_self_signed_cert(cert_dir_path, "server")
        cls.untrusted_cert, _ = _generate_self_signed_cert(cert_dir_path, "rogue")

    @classmethod
    def tearDownClass(cls):
        cls._cert_dir.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        tls_ctx = create_server_context(str(self.server_cert), str(self.server_key))
        self.server = CollaborationServer(
            "127.0.0.1",
            0,
            tls_ctx,
            AuthService(UserStore(self.root / "users.sqlite3")),
            idle_timeout=30,
        )
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        deadline = time.monotonic() + 3.0
        while self.server._listener is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIsNotNone(self.server._listener)
        self.port = self.server._listener.getsockname()[1]
        self.clients: list[ClientConnection] = []

    def tearDown(self):
        for conn in self.clients:
            conn.close()
        self.server.shutdown()
        self.server_thread.join(timeout=3)
        self.temp.cleanup()

    def _connect_user(self, username: str, *, on_event=None) -> ClientConnection:
        client_tls = create_client_context(str(self.server_cert))
        conn = ClientConnection(
            "127.0.0.1",
            self.port,
            client_tls,
            server_hostname="localhost",
            on_event=on_event,
        )
        conn.connect()
        self.clients.append(conn)
        reg = conn.request("register", username=username, password="correct horse battery")
        self.assertTrue(reg["ok"])
        login = conn.request("login", username=username, password="correct horse battery")
        self.assertTrue(login["ok"])
        return conn

    def test_rejects_untrusted_tls_certificate(self):
        bad_client_tls = create_client_context(str(self.untrusted_cert))
        conn = ClientConnection("127.0.0.1", self.port, bad_client_tls, server_hostname="localhost")
        with self.assertRaises(ssl.SSLError):
            conn.connect()

    def test_end_to_end_multichunk_and_empty_file_transfer_over_tls(self):
        bob_dl = self.root / "bob_downloads"
        alice_conn = self._connect_user("alice")
        bob_conn = self._connect_user("bob")

        sender = FileSender(alice_conn.request, chunk_size=32_768)
        receiver = FileReceiver(bob_conn.request, download_dir=bob_dl, auto_accept=True)
        alice_conn.on_event = sender.handle_event
        bob_conn.on_event = receiver.handle_event

        # 1. Multi-chunk binary file (~210 KB -> 7 chunks)
        src_file = self.root / "archive.bin"
        raw_bytes = os.urandom(210_123)
        src_file.write_bytes(raw_bytes)

        progress_updates = []
        sender.on_progress = lambda p: progress_updates.append(p.percent)
        outcome = sender.send_blocking(src_file, "bob", timeout=15.0)
        self.assertTrue(outcome["ok"], msg=str(outcome))

        received_file = bob_dl / "archive.bin"
        self.assertTrue(received_file.is_file())
        self.assertEqual(received_file.stat().st_size, len(raw_bytes))
        self.assertEqual(
            hashlib.sha256(received_file.read_bytes()).hexdigest(),
            hashlib.sha256(raw_bytes).hexdigest(),
        )
        self.assertGreaterEqual(len(progress_updates), 1)

        # 2. Empty 0-byte file
        empty_src = self.root / "empty.dat"
        empty_src.write_bytes(b"")
        outcome_empty = sender.send_blocking(empty_src, "bob", timeout=10.0)
        self.assertTrue(outcome_empty["ok"])
        self.assertEqual((bob_dl / "empty.dat").read_bytes(), b"")

    def test_recipient_reject_and_offer_timeout(self):
        bob_dl = self.root / "bob_reject"
        alice_conn = self._connect_user("alice")
        bob_conn = self._connect_user("bob")

        offer_arrived = threading.Event()
        offered_ids: list[str] = []

        sender = FileSender(alice_conn.request, offer_timeout=1.2)
        receiver = FileReceiver(
            bob_conn.request,
            download_dir=bob_dl,
            auto_accept=False,
            on_offer=lambda m, sender_name: (offered_ids.append(m.transfer_id), offer_arrived.set()),
        )
        alice_conn.on_event = sender.handle_event
        bob_conn.on_event = receiver.handle_event

        sample = self.root / "doc.txt"
        sample.write_text("hello bob", encoding="utf-8")

        # Explicit reject
        manifest = sender.start_send(sample, "bob")
        self.assertTrue(offer_arrived.wait(3.0))
        receiver.reject(offered_ids[0])
        rejected_outcome = sender.wait(manifest.transfer_id, timeout=5.0)
        self.assertFalse(rejected_outcome["ok"])
        self.assertEqual(rejected_outcome["code"], "rejected")

        # Offer timeout when recipient ignores offer
        self.server.transfers.offer_timeout = 0.5
        manifest2 = sender.start_send(sample, "bob")
        time.sleep(0.7)
        self.server.transfers.reap_expired()
        timeout_outcome = sender.wait(manifest2.transfer_id, timeout=3.0)
        self.assertFalse(timeout_outcome["ok"])

    def test_mid_transfer_disconnect_cleans_up_partial_file_and_keeps_server_healthy(self):
        bob_dl = self.root / "bob_partial"
        alice_conn = self._connect_user("alice")
        bob_conn = self._connect_user("bob")
        charlie_conn = self._connect_user("charlie")

        chunk_written = threading.Event()
        receiver = FileReceiver(
            bob_conn.request,
            download_dir=bob_dl,
            auto_accept=True,
            on_progress=lambda p: chunk_written.set() if p.chunks_done >= 1 else None,
        )
        bob_conn.on_event = receiver.handle_event

        # Manually initiate an offer + 1 chunk of a 3-chunk file, then abruptly drop Alice
        data = b"x" * 150_000
        digest = hashlib.sha256(data).hexdigest()
        tid = "11111111-2222-4333-8444-555555555555"
        offer_res = alice_conn.request(
            "file_offer",
            transfer_id=tid,
            to="bob",
            filename="interrupted.bin",
            size=len(data),
            sha256=digest,
            chunk_size=65_536,
            total_chunks=3,
        )
        self.assertTrue(offer_res["ok"])

        # Wait briefly for Bob's auto-accept to register on server
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            import base64

            res = alice_conn.request(
                "file_chunk",
                transfer_id=tid,
                index=0,
                data=base64.b64encode(data[:65_536]).decode("ascii"),
            )
            if res.get("ok"):
                break
            time.sleep(0.05)

        self.assertTrue(chunk_written.wait(3.0))
        # Abruptly close Alice's socket mid-transfer
        alice_conn.close()

        # Wait for server disconnect notification to clean up Bob's .part file
        deadline = time.monotonic() + 3.0
        while list(bob_dl.glob("*.part")) and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertEqual(list(bob_dl.glob("*")), [])
        # Server remains healthy: Charlie can still chat with Bob
        chat_res = charlie_conn.request("chat_send", to="bob", text="Server still alive!")
        self.assertTrue(chat_res["ok"])

    def test_twelve_concurrent_clients_chat_and_file_transfer(self):
        num_clients = 12
        inbox_counts = {f"user{i}": 0 for i in range(num_clients)}
        lock = threading.Lock()
        conns = {}

        for i in range(num_clients):
            uname = f"user{i}"

            def make_handler(u):
                def _on_event(msg):
                    if msg.get("type") == "chat_message":
                        with lock:
                            inbox_counts[u] += 1

                return _on_event

            conns[uname] = self._connect_user(uname, on_event=make_handler(uname))

        # Broadcast from user0 reaches all other 11 clients
        res = conns["user0"].request("chat_send", to=None, text="broadcast to 12 clients")
        self.assertTrue(res["ok"])

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            with lock:
                if sum(inbox_counts.values()) == num_clients - 1:
                    break
            time.sleep(0.02)

        with lock:
            self.assertEqual(sum(inbox_counts.values()), num_clients - 1)

        # Simultaneous file transfers between 3 pairs while 12 clients stay connected
        errors = []

        def transfer_pair(idx: int):
            try:
                s_name = f"user{idx}"
                r_name = f"user{idx + 6}"
                dl_dir = self.root / f"dl_{r_name}"
                sender = FileSender(conns[s_name].request, chunk_size=32_768)
                receiver = FileReceiver(conns[r_name].request, download_dir=dl_dir, auto_accept=True)
                conns[s_name].on_event = sender.handle_event
                conns[r_name].on_event = receiver.handle_event
                src = self.root / f"payload_{idx}.bin"
                src.write_bytes(os.urandom(80_000))
                out = sender.send_blocking(src, r_name, timeout=15.0)
                if not out.get("ok"):
                    errors.append(f"Pair {idx} failed: {out}")
                elif (dl_dir / src.name).read_bytes() != src.read_bytes():
                    errors.append(f"Pair {idx} content mismatch")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

        threads = [threading.Thread(target=transfer_pair, args=(i,)) for i in range(1, 4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
