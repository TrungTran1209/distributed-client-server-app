"""Unit tests for chat widgets, transfer widgets, ChatView and MainWindow wiring (offscreen Qt)."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from collab.transfer.manifest import TransferProgress


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _progress(done=1, total=4, bytes_done=65536, total_bytes=262144, direction="send"):
    return TransferProgress(
        transfer_id="3f2b8c1e-9a4d-4c55-8f0e-1b2c3d4e5f60",
        filename="a.bin",
        peer="bob",
        direction=direction,
        chunks_done=done,
        total_chunks=total,
        bytes_done=bytes_done,
        total_bytes=total_bytes,
    )


USERS = [
    {"username": "alice", "host": "1.1.1.1", "port": 1},
    {"username": "bob", "host": None, "port": None},
    {"username": "carol", "host": "3.3.3.3", "port": 3},
]


class TestFormatting:
    def test_human_size(self):
        from collab.gui.widgets.formatting import human_size

        assert human_size(0) == "0 B"
        assert human_size(1536) == "1.5 KB"
        assert human_size(67_108_864) == "64.0 MB"

    def test_sanitize_strips_control_chars(self):
        from collab.gui.widgets.formatting import sanitize

        assert sanitize("a\x01b\x1b[31mc\x07") == "ab[31mc"
        assert sanitize("tab\tok") == "tab\tok"
        assert sanitize(None) == ""


class TestUserList:
    def test_set_users_shows_broadcast_plus_users(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_users(USERS)
        assert w.count() == 4

    def test_default_selection_is_broadcast(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_users(USERS)
        assert w.get_selected_recipient() is None

    def test_select_user_returns_username_and_emits(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_users(USERS)
        seen = []
        w.recipient_changed.connect(seen.append)
        w.select_user("bob")
        assert w.get_selected_recipient() == "bob"
        assert seen[-1] == "bob"

    def test_selection_survives_refresh_and_falls_back_when_user_leaves(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_users(USERS)
        w.select_user("bob")
        w.set_users(USERS)
        assert w.get_selected_recipient() == "bob"
        w.set_users([USERS[0]])
        assert w.get_selected_recipient() is None

    def test_own_username_excluded(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_own_username("alice")
        w.set_users(USERS)
        assert w.count() == 3
        assert "alice" not in w.usernames()

    def test_unknown_address_not_invented(self, qapp):
        from collab.gui.widgets.user_list import UserListWidget

        w = UserListWidget()
        w.set_users(USERS)
        texts = [w.item(i).text() for i in range(w.count())]
        assert not any("None" in t for t in texts)


class TestMessageBubble:
    def test_own_message_flag(self, qapp):
        from collab.gui.widgets.message_bubble import MessageBubble

        own = MessageBubble("hi", "alice", "10:00", is_own=True, is_private=False)
        other = MessageBubble("hi", "bob", "10:00", is_own=False, is_private=False)
        assert own.property("own") is True
        assert other.property("own") is False

    def test_text_is_sanitized_and_not_html(self, qapp):
        from collab.gui.widgets.message_bubble import MessageBubble

        b = MessageBubble("<b>x</b>\x01\x02", "bob", "10:00", is_own=False, is_private=False)
        assert b.body_text() == "<b>x</b>"
        assert b.text_format() == Qt.TextFormat.PlainText

    def test_private_badge(self, qapp):
        from collab.gui.widgets.message_bubble import MessageBubble

        b = MessageBubble("s", "bob", "10:00", is_own=False, is_private=True)
        assert b.is_private_badge_shown()


class TestChatView:
    def _view(self, qapp):
        from collab.gui.views.chat_view import ChatView

        v = ChatView()
        v.set_connection_info("h", 1, "alice")
        v.set_users(USERS)
        return v

    def test_add_message_appends_bubble(self, qapp):
        v = self._view(qapp)
        v.add_message({"type": "chat_message", "from": "bob", "to": None, "text": "hello"})
        assert v.message_count() == 1

    def test_send_emits_with_recipient_and_clears(self, qapp):
        v = self._view(qapp)
        got = []
        v.send_requested.connect(lambda t, r: got.append((t, r)))
        v._input.setPlainText("hi all")
        v._btn_send.click()
        assert got == [("hi all", None)]
        assert v._input.toPlainText() == ""

    def test_send_private_uses_selected_user(self, qapp):
        v = self._view(qapp)
        v._users.select_user("bob")
        got = []
        v.send_requested.connect(lambda t, r: got.append((t, r)))
        v._input.setPlainText("psst")
        v._btn_send.click()
        assert got == [("psst", "bob")]

    def test_enter_sends_shift_enter_newline(self, qapp):
        v = self._view(qapp)
        got = []
        v.send_requested.connect(lambda t, r: got.append(t))
        v._input.setPlainText("line1")
        QTest.keyClick(v._input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
        assert got == []
        assert "\n" in v._input.toPlainText()
        QTest.keyClick(v._input, Qt.Key.Key_Return)
        assert len(got) == 1

    def test_empty_and_whitespace_blocked(self, qapp):
        v = self._view(qapp)
        got = []
        v.send_requested.connect(lambda t, r: got.append(t))
        v._input.setPlainText("   \n ")
        v._btn_send.click()
        assert got == []

    def test_over_limit_blocked(self, qapp):
        v = self._view(qapp)
        got = []
        v.send_requested.connect(lambda t, r: got.append(t))
        v._input.setPlainText("x" * 4001)
        v._btn_send.click()
        assert got == []
        assert not v._error_label.isHidden()

    def test_exactly_limit_allowed(self, qapp):
        v = self._view(qapp)
        got = []
        v.send_requested.connect(lambda t, r: got.append(t))
        v._input.setPlainText("x" * 4000)
        v._btn_send.click()
        assert len(got) == 1

    def test_disconnected_banner_disables_input(self, qapp):
        v = self._view(qapp)
        v.show_disconnected_banner("lost")
        assert not v._banner.isHidden()
        assert not v._input.isEnabled()
        assert not v._btn_send.isEnabled()
        assert not v._btn_file.isEnabled()
        v.hide_disconnected_banner()
        assert v._banner.isHidden()
        assert v._input.isEnabled()

    def test_file_button_needs_selected_user(self, qapp, monkeypatch):
        v = self._view(qapp)
        got = []
        v.file_send_requested.connect(lambda p, r: got.append((p, r)))
        v._btn_file.click()  # broadcast selected -> must not open a picker or emit
        assert got == []
        assert not v._error_label.isHidden()

    def test_persistent_history_notice_present(self, qapp):
        v = self._view(qapp)
        assert "lịch sử tin nhắn được lưu giữ" in v._notice.text().lower()

    def test_logout_signal(self, qapp):
        v = self._view(qapp)
        got = []
        v.logout_requested.connect(lambda: got.append(1))
        v._btn_logout.click()
        assert got == [1]


class TestTransferWidgets:
    def test_item_progress_updates_bar_and_text(self, qapp):
        from collab.gui.widgets.transfer_item import TransferItemWidget

        w = TransferItemWidget("tid", "a.bin", "bob", "send")
        w.update_progress(_progress(done=2, total=4, bytes_done=131072, total_bytes=262144))
        assert w.progress_value() == 50
        assert "128.0 KB" in w.bytes_text()

    def test_item_cancel_visible_only_while_active(self, qapp):
        from collab.gui.widgets.transfer_item import TransferItemWidget

        w = TransferItemWidget("tid", "a.bin", "bob", "send")
        assert not w._btn_cancel.isHidden()
        got = []
        w.cancel_requested.connect(got.append)
        w._btn_cancel.click()
        assert got == ["tid"]
        w.set_done(True, "/tmp/a.bin")
        assert w._btn_cancel.isHidden()
        assert w.is_finished()

    def test_item_failure_state(self, qapp):
        from collab.gui.widgets.transfer_item import TransferItemWidget

        w = TransferItemWidget("tid", "a.bin", "bob", "receive")
        w.set_done(False, None, "checksum_mismatch")
        assert w.is_finished()
        assert "checksum_mismatch" in w.status_text()

    def test_manager_routes_progress_and_completion(self, qapp):
        from collab.gui.widgets.transfer_manager import TransferManagerWidget

        m = TransferManagerWidget()
        m.add_outgoing("t1", "a.bin", "bob")
        m.add_incoming("t2", "b.bin", "carol")
        assert m.active_count() == 2
        m.update_progress("t1", _progress())
        m.set_transfer_done("t1", True, {"ok": True})
        assert m.active_count() == 1
        m.set_transfer_done("t2", False, {"ok": False, "code": "transfer_timeout"})
        assert m.active_count() == 0

    def test_manager_cancel_signal_forwarded(self, qapp):
        from collab.gui.widgets.transfer_manager import TransferManagerWidget

        m = TransferManagerWidget()
        m.add_outgoing("t1", "a.bin", "bob")
        got = []
        m.cancel_requested.connect(got.append)
        m._items["t1"]._btn_cancel.click()
        assert got == ["t1"]

    def test_offer_dialog_accept_reject(self, qapp):
        from collab.gui.widgets.transfer_dialog import TransferOfferDialog

        offer = {"transfer_id": "3f2b8c1e-9a4d-4c55-8f0e-1b2c3d4e5f60", "from": "bob",
                 "filename": "a.bin", "size": 70000, "total_chunks": 2, "expires_in_sec": 60}
        d = TransferOfferDialog(offer)
        acc, rej = [], []
        d.accepted_transfer.connect(acc.append)
        d.rejected_transfer.connect(lambda t, r: rej.append((t, r)))
        d._btn_accept.click()
        assert acc == [offer["transfer_id"]]
        d2 = TransferOfferDialog(offer)
        d2.rejected_transfer.connect(lambda t, r: rej.append((t, r)))
        d2._btn_reject.click()
        assert rej[0][0] == offer["transfer_id"]

    def test_offer_dialog_expires(self, qapp):
        from collab.gui.widgets.transfer_dialog import TransferOfferDialog

        d = TransferOfferDialog({"transfer_id": "x", "from": "b", "filename": "f", "size": 1,
                                 "total_chunks": 1, "expires_in_sec": 1})
        d.tick(5)
        assert not d._btn_accept.isEnabled()


class TestMainWindowWiring:
    def _win(self, qapp):
        from collab.gui.controllers.client_controller import ClientController
        from collab.gui.controllers.server_controller import ServerController
        from collab.gui.main_window import MainWindow

        return MainWindow(ServerController(), ClientController())

    def test_navigation(self, qapp):
        w = self._win(qapp)
        assert w.current_page() == "home"
        w.show_host()
        assert w.current_page() == "host"
        w.show_connect()
        assert w.current_page() == "connect"

    def test_min_size(self, qapp):
        w = self._win(qapp)
        assert w.minimumWidth() >= 1024 and w.minimumHeight() >= 680

    def test_client_signals_drive_ui(self, qapp):
        w = self._win(qapp)
        c = w.client_ctrl
        c.connected.emit({})
        assert w.current_page() == "auth"
        c.auth_succeeded.emit("alice")
        assert w.current_page() == "chat"
        c.users_updated.emit(USERS)
        assert w.chat_view._users.count() == 3  # own user excluded
        c.message_received.emit({"type": "chat_message", "from": "bob", "to": None, "text": "yo"})
        assert w.chat_view.message_count() == 1
        c.connection_lost.emit("boom")
        assert not w.chat_view._banner.isHidden()

    def test_login_failure_shows_error(self, qapp):
        w = self._win(qapp)
        w.client_ctrl.connected.emit({})
        w.client_ctrl.auth_failed.emit("Sai tên đăng nhập hoặc mật khẩu.")
        assert not w.auth_view._error_label.isHidden()

    def test_server_signals_drive_host_view(self, qapp):
        w = self._win(qapp)
        w.server_ctrl.server_started.emit()
        assert w.host_view.running
        w.server_ctrl.client_count_changed.emit(3)
        assert "3" in w.host_view._status_label.text()
        w.server_ctrl.server_stopped.emit()
        assert not w.host_view.running
        w.server_ctrl.server_error.emit("port busy")
        assert not w.host_view._error_label.isHidden()

    def test_offer_creates_dialog_state(self, qapp):
        w = self._win(qapp)
        w.client_ctrl.transfer_offer.emit({"transfer_id": "t", "from": "bob", "filename": "f",
                                           "size": 1, "total_chunks": 1, "expires_in_sec": 60})
        assert w.pending_offer_count() == 1

