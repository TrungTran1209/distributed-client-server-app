"""Unit tests for GUI controllers — must run BEFORE implementation (RED phase).

Environment: QT_QPA_PLATFORM=offscreen is set at module import time so that
PySide6 never tries to open a display.
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

# ── MUST set before any PySide6 import ──────────────────────────────────────
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication, QTimer

import sys

# Ensure there's a QApplication instance for the whole test run
_app = QApplication.instance() or QApplication(sys.argv)


# ── Helper: pump the Qt event loop briefly ──────────────────────────────────
def _pump(ms: int = 300) -> None:
    """Let the Qt event loop process pending signals for `ms` milliseconds."""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.01)


def _wait_signal(received: list, timeout: float = 5.0) -> bool:
    """Block until received list is non-empty or timeout expires."""
    deadline = time.monotonic() + timeout
    while not received and time.monotonic() < deadline:
        _app.processEvents()
        time.sleep(0.02)
    return bool(received)


# ── Cert paths ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).parent.parent.parent
_CERTS_DIR = _REPO_ROOT / "certs"
_SERVER_CERT = str(_CERTS_DIR / "server.crt")
_SERVER_KEY  = str(_CERTS_DIR / "server.key")


def _certs_available() -> bool:
    return Path(_SERVER_CERT).exists() and Path(_SERVER_KEY).exists()


# ============================================================================
# ServerController tests
# ============================================================================

class TestServerController(unittest.TestCase):
    """Tests for collab.gui.controllers.server_controller.ServerController."""

    def setUp(self):
        from collab.gui.controllers.server_controller import ServerController
        self.ctrl = ServerController()

    def tearDown(self):
        # Always stop if still running to avoid port-in-use on subsequent tests
        if self.ctrl.is_running():
            self.ctrl.stop_server()
        # Give server thread a moment to wind down
        time.sleep(0.1)

    def _config(self, port: int = 0, **overrides) -> dict:
        base = dict(
            host="127.0.0.1",
            port=port,
            udp_port=0,          # 0 → DiscoveryServer picks a random port
            advertise_host="127.0.0.1",
            cert=_SERVER_CERT,
            key=_SERVER_KEY,
            database=":memory:",
            idle_timeout=90,
            auth_timeout=60,
        )
        base.update(overrides)
        return base

    # ------------------------------------------------------------------
    @unittest.skipUnless(_certs_available(), "certs/server.{crt,key} not found")
    def test_server_controller_starts_and_stops(self):
        """start_server emits server_started, is_running() True; then stops cleanly."""
        started: list = []
        stopped: list = []
        self.ctrl.server_started.connect(lambda: started.append(True))
        self.ctrl.server_stopped.connect(lambda: stopped.append(True))

        self.ctrl.start_server(self._config())
        self.assertTrue(_wait_signal(started, timeout=5), "server_started not emitted")
        self.assertTrue(self.ctrl.is_running())

        self.ctrl.stop_server()
        self.assertTrue(_wait_signal(stopped, timeout=5), "server_stopped not emitted")
        self.assertFalse(self.ctrl.is_running())

    # ------------------------------------------------------------------
    def test_server_controller_error_on_bad_cert(self):
        """Nonexistent cert path → server_error signal emitted, never starts."""
        errors: list = []
        self.ctrl.server_error.connect(errors.append)

        self.ctrl.start_server(self._config(cert="/no/such/cert.pem", key="/no/such/key.pem"))
        self.assertTrue(_wait_signal(errors, timeout=5), "server_error not emitted")
        self.assertFalse(self.ctrl.is_running())
        self.assertIsInstance(errors[0], str)
        self.assertTrue(len(errors[0]) > 0)

    # ------------------------------------------------------------------
    @unittest.skipUnless(_certs_available(), "certs/server.{crt,key} not found")
    def test_server_controller_error_on_port_in_use(self):
        """Starting a second server on a busy port → server_error on second."""
        # Grab a known-free port first
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        busy_port = probe.getsockname()[1]
        probe.close()

        from collab.gui.controllers.server_controller import ServerController
        ctrl1 = ServerController()
        ctrl2 = ServerController()
        try:
            started1: list = []
            errors2: list  = []
            ctrl1.server_started.connect(lambda: started1.append(True))
            ctrl2.server_error.connect(errors2.append)

            ctrl1.start_server(self._config(port=busy_port))
            self.assertTrue(_wait_signal(started1, timeout=5), "ctrl1 server_started not emitted")

            ctrl2.start_server(self._config(port=busy_port))
            self.assertTrue(_wait_signal(errors2, timeout=5), "ctrl2 server_error not emitted")
        finally:
            ctrl1.stop_server()
            ctrl2.stop_server()
            time.sleep(0.1)


# ============================================================================
# ClientController tests
# ============================================================================

class TestClientController(unittest.TestCase):
    """Tests for collab.gui.controllers.client_controller.ClientController."""

    def setUp(self):
        from collab.gui.controllers.client_controller import ClientController
        self.ctrl = ClientController()

    def tearDown(self):
        self.ctrl.disconnect()
        time.sleep(0.05)

    # ------------------------------------------------------------------
    def test_client_controller_emits_connection_lost_on_bad_host(self):
        """Connecting to a nonexistent host emits connection_lost signal."""
        lost: list = []
        self.ctrl.connection_lost.connect(lost.append)

        import ssl
        tls_ctx = ssl.create_default_context()
        # Use a port that is almost certainly not listening on localhost
        self.ctrl.connect_to_server("127.0.0.1", 19999, tls_ctx, "/tmp")
        self.assertTrue(_wait_signal(lost, timeout=8), "connection_lost not emitted")
        self.assertIsInstance(lost[0], str)

    # ------------------------------------------------------------------
    def test_client_controller_dispatches_user_list_signal(self):
        """Injecting a user_list event via on_event → users_updated emitted."""
        from collab.gui.controllers.client_controller import ClientController

        ctrl = ClientController()
        updated: list = []
        ctrl.users_updated.connect(updated.append)

        # Simulate the on_event callback being called (as if the reader thread fired it)
        users = [{"username": "alice", "host": "h", "port": 1}, {"username": "bob", "host": "h", "port": 2}]
        event = {"type": "user_list", "users": users}
        ctrl._on_server_event(event)
        _pump(200)

        self.assertTrue(updated, "users_updated not emitted")
        self.assertEqual(updated[0], users)

    # ------------------------------------------------------------------
    def test_client_controller_dispatches_chat_signal(self):
        """Injecting a chat_message event → message_received emitted."""
        from collab.gui.controllers.client_controller import ClientController

        ctrl = ClientController()
        received: list = []
        ctrl.message_received.connect(received.append)

        event = {
            "type": "chat_message",
            "from": "alice",
            "to": None,
            "text": "hello world",
            "message_id": "abc123",
        }
        ctrl._on_server_event(event)
        _pump(200)

        self.assertTrue(received, "message_received not emitted")
        self.assertEqual(received[0]["from"], "alice")
        self.assertEqual(received[0]["text"], "hello world")

    # ------------------------------------------------------------------
    def test_client_controller_dispatches_transfer_offer(self):
        """Injecting a file_offer_event → transfer_offer signal emitted."""
        from collab.gui.controllers.client_controller import ClientController

        ctrl = ClientController()
        offers: list = []
        ctrl.transfer_offer.connect(offers.append)

        tid = "3f2b8c1e-9a4d-4c55-8f0e-1b2c3d4e5f60"
        event = {
            "type": "file_offer_event",
            "transfer_id": tid,
            "from": "bob",
            "filename": "data.txt",
            "size": 1024,
            "total_chunks": 1,
            "sha256": "a" * 64,
            "chunk_size": 1024,
            "expires_in_sec": 60,
        }
        ctrl._on_server_event(event)
        _pump(200)

        self.assertTrue(offers, "transfer_offer not emitted")
        self.assertEqual(offers[0]["transfer_id"], tid)
        self.assertEqual(offers[0]["from"], "bob")


# ============================================================================
# AsyncWorkers smoke tests
# ============================================================================

class TestAsyncWorkers(unittest.TestCase):
    """Basic instantiation and signal-wiring checks for QRunnable workers."""

    def test_worker_signals_object_exists(self):
        from collab.gui.workers.async_workers import WorkerSignals
        ws = WorkerSignals()
        # signals must be accessible
        self.assertTrue(hasattr(ws, "finished"))
        self.assertTrue(hasattr(ws, "error"))
        self.assertTrue(hasattr(ws, "result"))

    def test_connect_worker_is_qrunnable(self):
        from collab.gui.workers.async_workers import ConnectWorker
        from PySide6.QtCore import QRunnable
        import ssl
        ctx = MagicMock(spec=ssl.SSLContext)
        worker = ConnectWorker("127.0.0.1", 9999, ctx, "/tmp")
        self.assertIsInstance(worker, QRunnable)

    def test_auth_worker_is_qrunnable(self):
        from collab.gui.workers.async_workers import AuthWorker
        from PySide6.QtCore import QRunnable
        conn = MagicMock()
        worker = AuthWorker(conn, "login", "user", "pass")
        self.assertIsInstance(worker, QRunnable)

    def test_chat_worker_is_qrunnable(self):
        from collab.gui.workers.async_workers import ChatWorker
        from PySide6.QtCore import QRunnable
        conn = MagicMock()
        worker = ChatWorker(conn, to=None, text="hi")
        self.assertIsInstance(worker, QRunnable)

    def test_discovery_worker_is_qrunnable(self):
        from collab.gui.workers.async_workers import DiscoveryWorker
        from PySide6.QtCore import QRunnable
        worker = DiscoveryWorker(udp_port=37020)
        self.assertIsInstance(worker, QRunnable)

    def test_file_send_worker_is_qrunnable(self):
        from collab.gui.workers.async_workers import FileSendWorker
        from PySide6.QtCore import QRunnable
        sender = MagicMock()
        worker = FileSendWorker(sender, "/tmp/file.txt", "alice")
        self.assertIsInstance(worker, QRunnable)


if __name__ == "__main__":
    unittest.main()
