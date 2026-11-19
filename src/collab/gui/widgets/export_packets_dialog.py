"""Wireshark-style Export Specified Packets dialog and packet range parser."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)


def parse_packet_range(text: str, valid_packet_nos: set[int]) -> set[int]:
    """Parse Wireshark-style packet ranges like ``1-3, 5, 17-19`` into matching packet numbers."""
    raw = text.strip()
    if not raw:
        raise ValueError("Vui lòng nhập dải số gói tin (ví dụ: 1-5, 12, 17-19).")
    matched: set[int] = set()
    for token in raw.split(","):
        part = token.strip()
        if not part:
            raise ValueError(f"Cú pháp dải gói tin không hợp lệ: '{text}'")
        if "-" in part:
            bounds = part.split("-")
            if len(bounds) != 2:
                raise ValueError(f"Dải gói tin không hợp lệ: '{part}'")
            try:
                start = int(bounds[0].strip())
                end = int(bounds[1].strip())
            except ValueError as exc:
                raise ValueError(f"Số gói tin phải là số nguyên dương: '{part}'") from exc
            if start <= 0 or end <= 0 or start > end:
                raise ValueError(f"Khoảng gói tin không hợp lệ ({start} > {end} hoặc <= 0).")
            for num in range(start, end + 1):
                if num in valid_packet_nos:
                    matched.add(num)
        else:
            try:
                num = int(part)
            except ValueError as exc:
                raise ValueError(f"Số gói tin phải là số nguyên dương: '{part}'") from exc
            if num <= 0:
                raise ValueError(f"Số gói tin phải > 0: '{part}'")
            if num in valid_packet_nos:
                matched.add(num)
    if not matched:
        raise ValueError("Không có gói tin nào khớp với dải số bạn nhập.")
    return matched


class ExportPacketsDialog(QDialog):
    """Choose which packets to export (Selected / Displayed / Range / All), like Wireshark."""

    def __init__(
        self,
        *,
        export_format: str,
        total_count: int,
        displayed_count: int,
        selected_count: int,
        valid_packet_nos: set[int],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._valid_nos = set(valid_packet_nos)
        self.setWindowTitle(f"Xuất gói tin chọn lọc ({export_format.upper()}) — Kiểu Wireshark")
        self.setMinimumWidth(460)

        intro = QLabel(
            f"Chọn phạm vi gói tin muốn xuất ra tệp {export_format.upper()} "
            "(giữ Ctrl hoặc Shift trên bảng để chọn nhiều gói):"
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("font-weight: 600; color: #334155;")

        self._rb_selected = QRadioButton(f"Các gói tin đang chọn ({selected_count} gói)")
        self._rb_selected.setEnabled(selected_count > 0)

        self._rb_displayed = QRadioButton(f"Các gói tin đang hiển thị theo bộ lọc ({displayed_count} gói)")
        self._rb_displayed.setEnabled(displayed_count > 0)

        self._rb_range = QRadioButton("Theo dải số thứ tự gói (No.):")
        self._rb_range.setEnabled(total_count > 0)
        self._range_edit = QLineEdit()
        self._range_edit.setPlaceholderText("Ví dụ: 1-5, 12, 17-19")
        self._range_edit.setMinimumHeight(32)
        self._range_edit.textChanged.connect(lambda _t: self._rb_range.setChecked(True))

        self._rb_all = QRadioButton(f"Tất cả gói tin đã bắt ({total_count} gói)")
        self._rb_all.setEnabled(total_count > 0)

        if selected_count > 0:
            self._rb_selected.setChecked(True)
        elif displayed_count > 0:
            self._rb_displayed.setChecked(True)
        else:
            self._rb_all.setChecked(True)

        range_row = QHBoxLayout()
        range_row.addWidget(self._rb_range)
        range_row.addWidget(self._range_edit, 1)

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()

        btn_cancel = QPushButton("Hủy")
        btn_cancel.clicked.connect(self.reject)
        self._btn_export = QPushButton(f"⬇ Tiếp tục xuất {export_format.upper()}…")
        self._btn_export.setObjectName("primary")
        self._btn_export.setEnabled(total_count > 0)
        self._btn_export.clicked.connect(self._on_accept)

        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(btn_cancel)
        actions.addWidget(self._btn_export)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(intro)
        layout.addWidget(self._rb_selected)
        layout.addWidget(self._rb_displayed)
        layout.addLayout(range_row)
        layout.addWidget(self._rb_all)
        layout.addWidget(self._error_label)
        layout.addLayout(actions)

    def selected_mode(self) -> str:
        if self._rb_selected.isChecked():
            return "selected"
        if self._rb_displayed.isChecked():
            return "displayed"
        if self._rb_range.isChecked():
            return "range"
        return "all"

    def range_text(self) -> str:
        return self._range_edit.text().strip()

    def _on_accept(self) -> None:
        if self.selected_mode() == "range":
            try:
                parse_packet_range(self.range_text(), self._valid_nos)
            except ValueError as exc:
                self._error_label.setText(str(exc))
                self._error_label.show()
                return
        self._error_label.hide()
        self.accept()
