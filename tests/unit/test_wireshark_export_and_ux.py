"""TDD tests for Wireshark-style selective packet export, readable Server config layout,
and Client disconnect UX (reconnect with prefilled username + logout/switch-server button).
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QAbstractItemView, QApplication, QGroupBox, QScrollArea


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication(sys.argv[:1])


def _sample_events() -> list[dict]:
    return [
        {"ts": "10:00:01.000", "category": "AUTH", "action": "login", "actor": "alice", "target": "127.0.0.1:5001"},
        {"ts": "10:00:02.000", "category": "CHAT", "action": "chat_direct", "actor": "alice", "target": "bob", "chars": 12},
        {
            "ts": "10:00:03.000",
            "category": "CHUNK",
            "action": "file_chunk",
            "actor": "alice",
            "target": "bob",
            "transfer_id": "11111111-1111-1111-1111-111111111111",
            "filename": "report.pdf",
            "chunk_index": 0,
            "total_chunks": 2,
            "chunk_bytes": 65536,
            "bytes_relayed": 65536,
            "total_bytes": 100000,
        },
        {
            "ts": "10:00:04.000",
            "category": "CHUNK",
            "action": "file_chunk",
            "actor": "alice",
            "target": "bob",
            "transfer_id": "11111111-1111-1111-1111-111111111111",
            "filename": "report.pdf",
            "chunk_index": 1,
            "total_chunks": 2,
            "chunk_bytes": 34464,
            "bytes_relayed": 100000,
            "total_bytes": 100000,
        },
        {
            "ts": "10:00:05.000",
            "category": "FILE",
            "action": "file_ack",
            "actor": "bob",
            "target": "alice",
            "transfer_id": "11111111-1111-1111-1111-111111111111",
            "filename": "report.pdf",
            "ok": True,
        },
    ]


class TestPacketRangeParserAndExportDialog:
    def test_parse_packet_range_handles_singles_and_ranges(self):
        from collab.gui.widgets.export_packets_dialog import parse_packet_range

        valid = {1, 2, 3, 4, 5, 6, 7, 8}
        assert parse_packet_range("1-3, 5, 7-8", valid) == {1, 2, 3, 5, 7, 8}
        assert parse_packet_range(" 4 ", valid) == {4}

    @pytest.mark.parametrize("bad", ["", "   ", "abc", "5-2", "0", "1-3-5", "99"])
    def test_parse_packet_range_rejects_invalid_inputs(self, bad):
        from collab.gui.widgets.export_packets_dialog import parse_packet_range

        with pytest.raises(ValueError):
            parse_packet_range(bad, {1, 2, 3, 4, 5})

    def test_export_dialog_defaults_to_selected_when_rows_selected(self, qapp):
        from collab.gui.widgets.export_packets_dialog import ExportPacketsDialog

        dlg = ExportPacketsDialog(
            export_format="CSV",
            total_count=5,
            displayed_count=4,
            selected_count=2,
            valid_packet_nos={1, 2, 3, 4, 5},
        )
        assert dlg.selected_mode() == "selected"

        dlg_none = ExportPacketsDialog(
            export_format="JSON",
            total_count=5,
            displayed_count=3,
            selected_count=0,
            valid_packet_nos={1, 2, 3, 4, 5},
        )
        assert dlg_none.selected_mode() == "displayed"


class TestServerSelectiveExportAndReadableLayout:
    def _populated_server_window(self, qapp):
        from collab.gui.controllers.server_controller import ServerController
        from collab.gui.server_window import ServerMainWindow

        ctrl = ServerController()
        win = ServerMainWindow(ctrl)
        for ev in _sample_events():
            ctrl.trace_recorded.emit(ev)
        return win

    def test_trace_table_supports_multi_selection_and_selective_export(self, qapp, tmp_path: Path):
        win = self._populated_server_window(qapp)
        assert win._trace_table.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection

        # Select ONLY rows 1 (packet #2) and 3 (packet #4)
        win._trace_table.clearSelection()
        sel = win._trace_table.selectionModel()
        from PySide6.QtCore import QItemSelectionModel

        for r in (1, 3):
            idx = win._trace_table.model().index(r, 0)
            sel.select(idx, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)

        selected_rows = win.resolve_export_rows("selected")
        assert selected_rows == [1, 3]
        assert "Đã chọn: 2" in win._stats_badge.text()

        # Export selected packets to CSV -> header + 2 rows ONLY
        csv_path = tmp_path / "selected.csv"
        win.write_packets_csv(str(csv_path), selected_rows)
        with open(csv_path, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3  # 1 header + 2 selected packets
        assert [r[0] for r in rows[1:]] == ["2", "4"]

        # Export selected packets to JSON -> 2 records ONLY
        json_path = tmp_path / "selected.json"
        win.write_packets_json(str(json_path), selected_rows)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert [d["packet_no"] for d in data] == [2, 4]

        # Displayed mode after filtering CHUNK -> ONLY packets #3 and #4
        win.set_trace_filter("CHUNK")
        displayed_rows = win.resolve_export_rows("displayed")
        assert displayed_rows == [2, 3]

        # Range mode ("1, 4-5") -> ONLY packets #1, #4, #5
        range_rows = win.resolve_export_rows("range", range_text="1, 4-5")
        assert range_rows == [0, 3, 4]

    def test_left_config_column_is_scrollable_tall_enough_and_has_no_broken_mnemonics(self, qapp):
        from collab.gui.controllers.server_controller import ServerController
        from collab.gui.server_window import ServerMainWindow

        win = ServerMainWindow(ServerController())

        # No QGroupBox title should contain an unescaped single '&' (which renders as '_' mnemonic)
        for box in win.findChildren(QGroupBox):
            title = box.title()
            stripped = title.replace("&&", "")
            assert "&" not in stripped, f"Unescaped '&' mnemonic in QGroupBox title: {title!r}"

        # Config widgets must have comfortable minimum height so text is never clipped vertically
        for widget in (
            win._host_edit,
            win._port_spin,
            win._udp_spin,
            win._cert_edit,
            win._key_edit,
            win._db_edit,
            win._idle_spin,
            win._auth_spin,
        ):
            assert widget.minimumHeight() >= 28

        # Left config panel is wrapped in a QScrollArea so small screens never squash inputs
        scroll_areas = win.findChildren(QScrollArea)
        assert len(scroll_areas) >= 1


class TestClientDisconnectUX:
    def test_disconnect_banner_has_reconnect_and_logout_actions_and_prefills_username(self, qapp):
        from collab.gui.client_window import ClientMainWindow
        from collab.gui.controllers.client_controller import ClientController

        ctrl = ClientController(auto_accept=True)
        win = ClientMainWindow(ctrl)

        ctrl.connected.emit({"server_name": "LumiChat"})
        ctrl.username = "alice"
        ctrl.auth_succeeded.emit("alice")
        assert win.current_page() == "chat"

        # Server drops connection with raw socket EOF text -> clean natural Vietnamese, no '&' mnemonic bug
        ctrl.connection_lost.emit("connection closed while reading frame")
        assert not win.chat_view._banner.isHidden()
        assert not win.chat_view._btn_reconnect.isHidden()
        assert not win.chat_view._btn_disconnect_logout.isHidden()
        assert "&" not in win.chat_view._btn_reconnect.text()
        assert "reading frame" not in win.chat_view._banner_text.text().lower()

        # Reconnect succeeds -> moves to auth page with username pre-filled, password empty
        ctrl.connected.emit({"server_name": "LumiChat"})
        assert win.current_page() == "auth"
        assert win.auth_view._login_user_edit.text() == "alice"
        assert win.auth_view._login_pass_edit.text() == ""

        # Return to chat, disconnect again, and click "Đăng xuất / Đổi máy chủ" -> goes to connect page
        ctrl.auth_succeeded.emit("alice")
        ctrl.connection_lost.emit("Máy chủ đã dừng")
        win.chat_view._btn_disconnect_logout.click()
        assert win.current_page() == "connect"
