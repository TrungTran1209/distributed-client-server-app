"""Extra GUI tests: certificate generation, error mapping, MainWindow flows."""
import os
import ssl
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _window(qapp):
    from collab.gui.controllers.client_controller import ClientController
    from collab.gui.controllers.server_controller import ServerController
    from collab.gui.main_window import MainWindow

    return MainWindow(ServerController(), ClientController())


class TestCertGeneration:
    def test_san_contains_requested_ip_and_dns_and_key_not_encrypted(self, tmp_path):
        from cryptography import x509
        from collab.gui.widgets.cert_gen_dialog import generate_self_signed

        cert_path, key_path = generate_self_signed(tmp_path, "localhost", ["192.168.1.10"], ["myhost"])
        cert = x509.load_pem_x509_certificate(open(cert_path, "rb").read())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert "192.168.1.10" in [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        assert {"localhost", "myhost"} <= set(san.get_values_for_type(x509.DNSName))
        # usable as both server cert and client CA
        ssl.create_default_context(cafile=cert_path)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)

    def test_invalid_ip_rejected(self, tmp_path):
        from collab.gui.widgets.cert_gen_dialog import generate_self_signed

        with pytest.raises(ValueError):
            generate_self_signed(tmp_path, "localhost", ["not-an-ip"], [])

    def test_dialog_generates_and_emits_paths(self, qapp, tmp_path):
        from collab.gui.widgets.cert_gen_dialog import CertGenDialog

        d = CertGenDialog()
        d._out.setText(str(tmp_path))
        got = []
        d.generated.connect(lambda c, k: got.append((c, k)))
        d._btn.click()
        assert got and os.path.exists(got[0][0]) and os.path.exists(got[0][1])

    def test_dialog_shows_error_for_bad_ip(self, qapp, tmp_path):
        from collab.gui.widgets.cert_gen_dialog import CertGenDialog

        d = CertGenDialog()
        d._out.setText(str(tmp_path))
        d._ips.setText("bogus")
        got = []
        d.generated.connect(lambda c, k: got.append(1))
        d._btn.click()
        assert not got and "Không tạo được" in d._result.text()


class TestFriendlyError:
    def test_ip_mismatch_mentions_san(self):
        from collab.gui.workers.async_workers import friendly_error

        exc = ssl.SSLCertVerificationError(1, "certificate verify failed: IP address mismatch")
        assert "SAN" in friendly_error(exc)

    def test_untrusted_cert(self):
        from collab.gui.workers.async_workers import friendly_error

        exc = ssl.SSLCertVerificationError(1, "certificate verify failed: self-signed certificate")
        assert "không đáng tin cậy" in friendly_error(exc)

    def test_refused_and_timeout(self):
        from collab.gui.workers.async_workers import friendly_error

        assert "từ chối" in friendly_error(ConnectionRefusedError())
        assert "hết thời gian" in friendly_error(TimeoutError())


class TestMainWindowFlows:
    def test_missing_ca_file_blocks_connect(self, qapp, tmp_path):
        w = _window(qapp)
        w._begin_connect("127.0.0.1", 37021, str(tmp_path / "nope.crt"), str(tmp_path))
        assert not w.connect_view._error_label.isHidden()
        assert w._endpoint is None

    def test_discovery_none_shows_message_found_adds_item(self, qapp):
        w = _window(qapp)
        w._on_discovery_finished(None)
        assert not w.connect_view._error_label.isHidden()
        w._on_discovery_finished({"server_name": "s", "host": "1.2.3.4", "tcp_port": 37021})
        assert w.connect_view._discovery_list.count() == 1

    def test_connection_lost_before_chat_returns_to_connect_page(self, qapp):
        w = _window(qapp)
        w.show_auth()
        w.client_ctrl.connection_lost.emit("down")
        assert w.current_page() == "connect"
        assert "down" in w.connect_view._error_label.text()

    def test_register_flow_switches_to_login_with_info(self, qapp):
        w = _window(qapp)
        w._register_user = "dave"
        w.client_ctrl.register_finished.emit(True, "")
        assert w.auth_view._login_user_edit.text() == "dave"
        assert not w.auth_view._info_label.isHidden()
        w.client_ctrl.register_finished.emit(False, "Tên đăng nhập đã tồn tại.")
        assert "tồn tại" in w.auth_view._error_label.text()

    def test_offer_dialog_closed_when_sender_cancels(self, qapp):
        w = _window(qapp)
        offer = {"transfer_id": "t1", "from": "bob", "filename": "f", "size": 1, "total_chunks": 1,
                 "expires_in_sec": 60}
        w.client_ctrl.transfer_offer.emit(offer)
        dialog = w._offers["t1"]
        w.client_ctrl.transfer_done.emit("t1", False, {"ok": False, "code": "transfer_cancelled"})
        assert not dialog._btn_accept.isEnabled()
        assert w.pending_offer_count() == 0

    def test_transfer_started_and_done_update_center(self, qapp):
        w = _window(qapp)
        w.client_ctrl.transfer_started.emit(
            {"direction": "send", "transfer_id": "t2", "filename": "a", "size": 1, "total_chunks": 1, "peer": "bob"})
        assert w.transfer_manager.active_count() == 1
        w.client_ctrl.transfer_done.emit("t2", True, {"ok": True})
        assert w.transfer_manager.active_count() == 0

    def test_chat_sent_echoes_own_message(self, qapp):
        w = _window(qapp)
        w.client_ctrl.username = "alice"
        w.chat_view.set_connection_info("h", 1, "alice")
        w.client_ctrl.chat_sent.emit(None, "hi")
        assert w.chat_view.message_count() == 1

    def test_stale_server_error_reenables_start(self, qapp):
        w = _window(qapp)
        w.server_ctrl.server_error.emit("Không thể mở cổng TCP 37021")
        assert w.host_view._btn_start.isEnabled()
