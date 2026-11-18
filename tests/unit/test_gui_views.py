"""
Unit tests for GUI views (Phase 2).
Run with QT_QPA_PLATFORM=offscreen.
"""
import os
import sys

# MUST set before any Qt import
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

# ---------------------------------------------------------------------------
# Shared QApplication fixture (one per session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


# ===========================================================================
# HomeView tests
# ===========================================================================

class TestHomeView:
    def test_home_view_signals_on_button_click(self, qapp):
        from collab.gui.views.home_view import HomeView

        view = HomeView()
        host_emitted = []
        join_emitted = []
        view.host_requested.connect(lambda: host_emitted.append(True))
        view.join_requested.connect(lambda: join_emitted.append(True))

        # Find buttons by clicking them
        view._btn_host.click()
        assert host_emitted, "host_requested signal not emitted on host button click"

        view._btn_join.click()
        assert join_emitted, "join_requested signal not emitted on join button click"

    def test_home_view_set_status(self, qapp):
        from collab.gui.views.home_view import HomeView

        view = HomeView()
        view.set_status("Server đang chạy", "success")
        assert not view._status_label.isHidden()
        text = view._status_label.text()
        assert "Server đang chạy" in text


# ===========================================================================
# HostView tests
# ===========================================================================

class TestHostView:
    def test_host_view_start_button_emits_config(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        # Provide cert/key paths to pass validation
        view._cert_edit.setText("server.crt")
        view._key_edit.setText("server.key")

        emitted = []
        view.start_requested.connect(lambda cfg: emitted.append(cfg))
        view._btn_start.click()

        assert emitted, "start_requested not emitted"
        cfg = emitted[0]
        assert "host" in cfg
        assert "port" in cfg

    def test_host_view_buttons_disabled_when_running(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        # Initially start is enabled, stop is disabled
        assert view._btn_start.isEnabled()
        assert not view._btn_stop.isEnabled()

        view.set_running(True)
        assert not view._btn_start.isEnabled()
        assert view._btn_stop.isEnabled()

        view.set_running(False)
        assert view._btn_start.isEnabled()
        assert not view._btn_stop.isEnabled()

    def test_host_view_append_log(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        view.append_log("Server started on port 37021")
        assert "Server started on port 37021" in view._log_edit.toPlainText()

    def test_host_view_set_client_count(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        view.set_running(True)
        view.set_client_count(3)
        assert "3" in view._status_label.text()

    def test_host_view_get_config(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        cfg = view.get_config()
        assert cfg["host"] == "0.0.0.0"
        assert cfg["port"] == 37021
        assert cfg["udp_port"] == 37020

    def test_host_view_start_validation_no_cert(self, qapp):
        from collab.gui.views.host_view import HostView

        view = HostView()
        view._cert_edit.setText("")
        view._key_edit.setText("")

        emitted = []
        view.start_requested.connect(lambda cfg: emitted.append(cfg))
        view._btn_start.click()

        assert not emitted, "start_requested should NOT be emitted when cert/key is empty"


# ===========================================================================
# ConnectView tests
# ===========================================================================

class TestConnectView:
    def test_connect_view_direct_connect(self, qapp):
        from collab.gui.views.connect_view import ConnectView

        view = ConnectView()
        view._host_edit.setText("192.168.1.100")
        view._port_spin.setValue(37021)

        emitted = []
        view.connect_requested.connect(lambda h, p, ca, dl: emitted.append((h, p, ca, dl)))
        view._btn_connect.click()

        assert emitted, "connect_requested not emitted"
        host, port, ca, dl = emitted[0]
        assert host == "192.168.1.100"
        assert port == 37021

    def test_connect_view_add_discovered(self, qapp):
        from collab.gui.views.connect_view import ConnectView

        view = ConnectView()
        view.add_discovered_server({
            "server_name": "test",
            "host": "1.2.3.4",
            "tcp_port": 37021,
        })
        assert view._discovery_list.count() == 1
        item_text = view._discovery_list.item(0).text()
        assert "1.2.3.4" in item_text

    def test_connect_view_clear_discovered(self, qapp):
        from collab.gui.views.connect_view import ConnectView

        view = ConnectView()
        view.add_discovered_server({"server_name": "s1", "host": "1.1.1.1", "tcp_port": 37021})
        view.clear_discovered()
        assert view._discovery_list.count() == 0

    def test_connect_view_set_discovering(self, qapp):
        from collab.gui.views.connect_view import ConnectView

        view = ConnectView()
        view.set_discovering(True)
        assert not view._btn_discover.isEnabled()
        view.set_discovering(False)
        assert view._btn_discover.isEnabled()

    def test_connect_view_discover_signal(self, qapp):
        from collab.gui.views.connect_view import ConnectView

        view = ConnectView()
        emitted = []
        view.discover_requested.connect(lambda p: emitted.append(p))
        view._btn_discover.click()

        assert emitted, "discover_requested not emitted"


# ===========================================================================
# AuthView tests
# ===========================================================================

class TestAuthView:
    def test_auth_view_login_signal(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view._login_user_edit.setText("alice")
        view._login_pass_edit.setText("secret123")

        emitted = []
        view.login_requested.connect(lambda u, p: emitted.append((u, p)))
        view._btn_login.click()

        assert emitted, "login_requested not emitted"
        user, pw = emitted[0]
        assert user == "alice"
        assert pw == "secret123"

    def test_auth_view_register_password_mismatch(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        # Switch to Register tab
        view._tabs.setCurrentIndex(1)
        view._reg_user_edit.setText("bob")
        view._reg_pass_edit.setText("pass1")
        view._reg_confirm_edit.setText("pass2")

        emitted = []
        view.register_requested.connect(lambda u, p: emitted.append((u, p)))
        view._btn_register.click()

        assert not emitted, "register_requested should NOT be emitted on password mismatch"
        # Error should be visible
        assert not view._error_label.isHidden()
        assert view._error_label.text() != ""

    def test_auth_view_empty_submit_prevented(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view._login_user_edit.setText("")
        view._login_pass_edit.setText("")

        emitted = []
        view.login_requested.connect(lambda u, p: emitted.append((u, p)))
        view._btn_login.click()

        assert not emitted, "login_requested should NOT be emitted with empty username"

    def test_auth_view_set_error(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view.set_error("Invalid credentials")
        assert not view._error_label.isHidden()
        assert "Invalid credentials" in view._error_label.text()

    def test_auth_view_clear_error(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view.set_error("some error")
        view.clear_error()
        assert view._error_label.isHidden()

    def test_auth_view_set_loading(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view.set_loading(True)
        assert not view._btn_login.isEnabled()
        view.set_loading(False)
        assert view._btn_login.isEnabled()

    def test_auth_view_clear_fields(self, qapp):
        from collab.gui.views.auth_view import AuthView

        view = AuthView()
        view._login_user_edit.setText("user")
        view._login_pass_edit.setText("pass")
        view.clear_fields()
        assert view._login_user_edit.text() == ""
        assert view._login_pass_edit.text() == ""

