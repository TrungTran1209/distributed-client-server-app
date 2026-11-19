"""TDD unit & integration tests for LumiChat Vibrant Light Theme, Split Server/Client GUIs,
Online/Offline User Tables, Persistent Offline Chat History, Chunk Trace Inspector, and Auto File Receive.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from collab.common.tls import create_client_context
from collab.gui.widgets.cert_gen_dialog import generate_self_signed


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _wait_until(qapp_inst, predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp_inst.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestVibrantLightThemeAndBranding:
    def test_theme_uses_white_light_background_and_vibrant_accents(self):
        from collab.gui.styles import theme

        assert theme.BG.upper() in {"#FFFFFF", "#F8FAFC", "#F9FAFB"}
        assert theme.SURFACE.upper() == "#FFFFFF"
        assert "#1e1e2e" not in theme.QSS.lower()
        assert "#181825" not in theme.QSS.lower()

    def test_lumichat_brand_package_entrypoints_exist(self):
        import lumichat
        from lumichat import client, server

        assert lumichat.APP_NAME == "LumiChat"
        assert callable(server.main)
        assert callable(client.main)


class TestSeparateServerAndClientWindows:
    def test_server_window_has_no_chat_client_pages_and_traces_chunks(self, qapp):
        from collab.gui.controllers.server_controller import ServerController
        from collab.gui.server_window import ServerMainWindow

        ctrl = ServerController()
        win = ServerMainWindow(ctrl)

        assert "LumiChat" in win.windowTitle()
        assert "Server" in win.windowTitle()
        assert not hasattr(win, "chat_view")
        assert not hasattr(win, "connect_view")

        # Emit directory snapshot (1 online, 1 offline)
        ctrl.directory_updated.emit(
            [
                {"username": "alice", "online": True, "host": "127.0.0.1", "port": 50100},
                {"username": "bob", "online": False, "host": None, "port": None},
            ]
        )
        assert win.online_user_count() == 1
        assert win.offline_user_count() == 1

        # Emit chunk trace and auth trace -> appears in trace table & supports category filter
        ctrl.trace_recorded.emit(
            {
                "ts": "12:00:01.100",
                "category": "AUTH",
                "action": "login",
                "actor": "alice",
                "target": "127.0.0.1:50100",
            }
        )
        ctrl.trace_recorded.emit(
            {
                "ts": "12:00:02.250",
                "category": "CHUNK",
                "action": "file_chunk",
                "actor": "alice",
                "target": "bob",
                "transfer_id": "3f2b8c1e-9a4d-4c55-8f0e-1b2c3d4e5f60",
                "filename": "report.pdf",
                "chunk_index": 0,
                "total_chunks": 4,
                "chunk_bytes": 65536,
                "bytes_relayed": 65536,
                "total_bytes": 200000,
            }
        )
        assert win.trace_row_count() == 2
        win.set_trace_filter("CHUNK")
        assert win.visible_trace_row_count() == 1
        win.set_trace_filter("ALL")
        assert win.visible_trace_row_count() == 2

        # Wireshark 3-pane inspection: select row -> updates dissection tree & hex dump
        win._trace_table.selectRow(1)
        win._on_packet_selected()
        assert win._details_tree.topLevelItemCount() > 0
        assert "Frame" in win._details_tree.topLevelItem(0).text(0)
        assert "0000" in win._hex_edit.toPlainText()

        # Test Wireshark shorthand filters
        win._search_edit.setText("collab.chunk")
        assert win.visible_trace_row_count() == 1
        win._search_edit.setText("collab.auth")
        assert win.visible_trace_row_count() == 1
        win._search_edit.setText("")
        assert win.visible_trace_row_count() == 2

        # Test pause / resume capture
        win._toggle_pause_capture()
        assert win._capture_paused is True
        ctrl.trace_recorded.emit({"action": "ping", "category": "SESSION"})
        assert win.trace_row_count() == 2  # dropped while paused
        win._toggle_pause_capture()
        assert win._capture_paused is False

    def test_client_window_has_no_host_server_page_and_no_offer_modal(self, qapp, tmp_path):
        from collab.gui.client_window import ClientMainWindow
        from collab.gui.controllers.client_controller import ClientController

        ctrl = ClientController(auto_accept=False)
        win = ClientMainWindow(ctrl)

        assert "LumiChat" in win.windowTitle()
        assert not hasattr(win, "host_view")
        assert win.current_page() == "connect"
        assert ctrl.file_receiver.auto_accept is False

        # Exercise ClientMainWindow signal flows (connect, auth, directory, history, offline notice, transfers, disconnect)
        win._begin_connect("127.0.0.1", 37021, "/no/such/ca.crt", "downloads")
        assert not win.connect_view._error_label.isHidden()

        ctrl.discovery_finished.emit(None)
        assert not win.connect_view._error_label.isHidden()
        ctrl.discovery_finished.emit({"server_name": "LumiChat", "host": "127.0.0.1", "tcp_port": 37021})
        assert win.connect_view._discovery_list.count() == 1

        ctrl.connected.emit({"server_name": "LumiChat"})
        assert win.current_page() == "auth"

        win._register_user = "alice"
        ctrl.register_finished.emit(True, "")
        assert win.auth_view._login_user_edit.text() == "alice"
        ctrl.auth_failed.emit("Sai mật khẩu")
        assert not win.auth_view._error_label.isHidden()

        ctrl.username = "alice"
        win._download_root = tmp_path / "downloads"
        ctrl.auth_succeeded.emit("alice")
        assert win.current_page() == "chat"
        assert ctrl.file_receiver.download_dir == tmp_path / "downloads" / "alice"

        ctrl.directory_updated.emit(
            [
                {"username": "alice", "online": True, "host": "127.0.0.1", "port": 1},
                {"username": "bob", "online": False, "host": None, "port": None},
            ]
        )
        ctrl.history_loaded.emit(
            [{"message_id": "m1", "from": "bob", "to": "alice", "text": "Chào Alice", "sent_at": "09:15"}]
        )
        ctrl.chat_sent.emit("bob", "Chào lại Bob")
        ctrl.chat_queued_offline.emit("bob")
        assert not win.chat_view._info_banner.isHidden()

        ctrl.transfer_started.emit(
            {
                "direction": "receive",
                "transfer_id": "t-auto",
                "filename": "report.pdf",
                "size": 1024,
                "total_chunks": 1,
                "peer": "bob",
            }
        )
        assert win.transfer_manager.active_count() == 1
        ctrl.transfer_done.emit("t-auto", True, {"ok": True, "filename": "report.pdf", "path": "/tmp/report.pdf"})
        assert win.transfer_manager.active_count() == 0

        ctrl.connection_lost.emit("Mất mạng")
        assert not win.chat_view._banner.isHidden()


class TestOnlineOfflineTablesAndConversationHistory:
    def test_user_list_separates_online_and_offline_tables_and_allows_selecting_offline(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_own_username("alice")
        w.set_directory(
            [
                {"username": "alice", "online": True, "host": "127.0.0.1", "port": 1},
                {"username": "bob", "online": True, "host": "127.0.0.1", "port": 2},
                {"username": "carol", "online": False, "host": None, "port": None},
                {"username": "dave", "online": False, "host": None, "port": None},
            ]
        )

        assert w.online_usernames() == ["alice", "bob"]
        assert w.offline_usernames() == ["carol", "dave"]

        # Select offline user carol -> allowed for messaging!
        w.select_user("carol")
        assert w.get_selected_recipient() == "carol"
        assert w.is_selected_online() is False

        # Select online user bob
        w.select_user("bob")
        assert w.get_selected_recipient() == "bob"
        assert w.is_selected_online() is True

        # Select broadcast channel
        w.select_user(None)
        assert w.get_selected_recipient() is None

    def test_chat_view_switches_conversations_and_restores_history(self, qapp):
        from collab.gui.views.chat_view import ChatView

        v = ChatView()
        v.set_connection_info("127.0.0.1", 37021, "alice")
        v.set_directory(
            [
                {"username": "alice", "online": True, "host": "127.0.0.1", "port": 1},
                {"username": "bob", "online": True, "host": "127.0.0.1", "port": 2},
                {"username": "carol", "online": False, "host": None, "port": None},
            ]
        )

        v.load_history(
            [
                {"message_id": "1", "from": "bob", "to": None, "text": "Chào kênh chung", "sent_at": "10:00"},
                {"message_id": "2", "from": "alice", "to": "carol", "text": "Nhắn Carol lúc offline", "sent_at": "10:01"},
                {"message_id": "3", "from": "bob", "to": "alice", "text": "Chào riêng Alice", "sent_at": "10:02"},
            ]
        )

        # Default is broadcast channel -> 1 message
        assert v.message_count() == 1

        # Switch to offline user carol -> sees the 1-1 message with carol AND can send new message!
        v._users.select_user("carol")
        assert v.message_count() == 1
        sent = []
        v.send_requested.connect(lambda text, to: sent.append((text, to)))
        v._input.setPlainText("Tin nhắn thêm cho Carol")
        v._btn_send.click()
        assert sent == [("Tin nhắn thêm cho Carol", "carol")]

        # Switch to online user bob -> sees Bob's 1-1 message
        v._users.select_user("bob")
        assert v.message_count() == 1

    def test_chat_view_broadcast_file_targets_online_users(self, qapp, monkeypatch):
        from collab.gui.views import chat_view
        from collab.gui.views.chat_view import ChatView

        view = ChatView()
        view.set_connection_info("127.0.0.1", 37021, "alice")
        view.set_directory(
            [
                {"username": "alice", "online": True, "host": "127.0.0.1", "port": 1},
                {"username": "bob", "online": True, "host": "127.0.0.1", "port": 2},
                {"username": "carol", "online": False, "host": None, "port": None},
            ]
        )
        sent = []
        view.file_send_requested.connect(lambda path, recipients: sent.append((path, recipients)))
        monkeypatch.setattr(chat_view.QFileDialog, "getOpenFileName", lambda *_args: ("report.pdf", ""))

        view._on_file()

        assert sent == [("report.pdf", ["bob"])]


class TestEndToEndOfflineChatHistoryAutoFileAndChunkTrace:
    def test_e2e_offline_chat_history_auto_file_and_server_chunk_trace(self, qapp):
        from collab.gui.controllers.client_controller import ClientController
        from collab.gui.controllers.server_controller import ServerController

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cert, key = generate_self_signed(root / "certs", "localhost", ["127.0.0.1"], ["localhost"])

            server = ServerController()
            traces: list[dict] = []
            started = []
            server.trace_recorded.connect(traces.append)
            server.server_started.connect(lambda: started.append(True))
            server.start_server(
                {
                    "host": "127.0.0.1",
                    "port": 0,
                    "udp_port": 0,
                    "cert": cert,
                    "key": key,
                    "database": str(root / "lumichat.sqlite3"),
                    "idle_timeout": 90,
                    "auth_timeout": 60,
                }
            )
            assert _wait_until(qapp, lambda: bool(started)), "server failed to start"
            port = server.tcp_port
            assert port is not None

            try:
                # 1. Bob registers then disconnects (so Bob is an offline registered user)
                bob_init = ClientController()
                c_ok, r_ok = [], []
                bob_init.connected.connect(c_ok.append)
                bob_init.register_finished.connect(lambda ok, msg: r_ok.append(ok))
                bob_init.connect_to_server(
                    "127.0.0.1", port, create_client_context(cert), str(root / "dl-bob"), udp_port=None
                )
                assert _wait_until(qapp, lambda: bool(c_ok))
                bob_init.register("bob", "password-123")
                assert _wait_until(qapp, lambda: bool(r_ok)) and r_ok[0] is True
                bob_init.shutdown_blocking()

                # 2. Alice connects, registers, logs in -> sees bob as OFFLINE in directory, messages bob offline
                alice = ClientController()
                a_conn, a_reg, a_auth, a_sent = [], [], [], []
                alice.connected.connect(a_conn.append)
                alice.register_finished.connect(lambda ok, msg: a_reg.append(ok))
                alice.auth_succeeded.connect(a_auth.append)
                alice.chat_sent.connect(lambda to, text: a_sent.append((to, text)))
                alice.connect_to_server(
                    "127.0.0.1", port, create_client_context(cert), str(root / "dl-alice"), udp_port=None
                )
                assert _wait_until(qapp, lambda: bool(a_conn))
                alice.register("alice", "password-123")
                assert _wait_until(qapp, lambda: bool(a_reg))
                alice.login("alice", "password-123")
                assert _wait_until(qapp, lambda: bool(a_auth))

                assert _wait_until(
                    qapp,
                    lambda: any(u["username"] == "bob" and not u["online"] for u in alice.get_directory()),
                )

                alice.send_chat("bob", "Chào Bob, mình nhắn lúc bạn đang offline nhé!")
                assert _wait_until(qapp, lambda: len(a_sent) == 1)

                # 3. Bob comes back online -> automatically loads chat_history containing Alice's offline message!
                bob = ClientController()
                b_conn, b_auth, b_hist, b_done, a_done = [], [], [], [], []
                bob.connected.connect(b_conn.append)
                bob.auth_succeeded.connect(b_auth.append)
                bob.history_loaded.connect(b_hist.append)
                bob.transfer_done.connect(lambda tid, ok, d: b_done.append((ok, d)))
                alice.transfer_done.connect(lambda tid, ok, d: a_done.append((ok, d)))

                dl_bob = root / "dl-bob-live"
                dl_bob.mkdir()
                bob.connect_to_server(
                    "127.0.0.1", port, create_client_context(cert), str(dl_bob), udp_port=None
                )
                assert _wait_until(qapp, lambda: bool(b_conn))
                bob.login("bob", "password-123")
                assert _wait_until(qapp, lambda: bool(b_auth))
                assert _wait_until(qapp, lambda: bool(b_hist))
                assert any(
                    m["text"] == "Chào Bob, mình nhắn lúc bạn đang offline nhé!" for m in b_hist[0]
                )

                # 4. Alice sends a 150 KB multi-chunk file to Bob -> Bob AUTO-ACCEPTS without clicking Accept!
                payload = os.urandom(150_000)  # 3 chunks
                src_file = root / "slides.bin"
                src_file.write_bytes(payload)
                alice.send_file(str(src_file), "bob")

                assert _wait_until(qapp, lambda: bool(a_done) and bool(b_done), timeout=15.0)
                assert a_done[0][0] is True and b_done[0][0] is True
                saved_path = Path(b_done[0][1]["path"])
                assert hashlib.sha256(saved_path.read_bytes()).hexdigest() == hashlib.sha256(payload).hexdigest()

                # 5. ServerController recorded all 3 chunk traces!
                assert _wait_until(
                    qapp,
                    lambda: len([t for t in traces if t.get("action") == "file_chunk"]) == 3,
                )

                bob.shutdown_blocking()
                alice.shutdown_blocking()
            finally:
                server.stop_server()
