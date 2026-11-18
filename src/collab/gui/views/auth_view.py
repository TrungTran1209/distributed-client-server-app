"""Login / registration screen."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


def _password() -> QLineEdit:
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    return edit


class AuthView(QWidget):
    login_requested = Signal(str, str)
    register_requested = Signal(str, str)
    back_requested = Signal()

    MIN_PASSWORD, MAX_PASSWORD = 8, 128

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._login_user_edit = QLineEdit()
        self._login_pass_edit = _password()
        self._btn_login = QPushButton("Đăng nhập")
        self._btn_login.setObjectName("primary")
        self._btn_login.clicked.connect(self._on_login)
        self._login_pass_edit.returnPressed.connect(self._btn_login.click)

        login_form = QFormLayout()
        login_form.addRow("Tên đăng nhập", self._login_user_edit)
        login_form.addRow("Mật khẩu", self._login_pass_edit)
        login = QWidget()
        login_lay = QVBoxLayout(login)
        login_lay.addLayout(login_form)
        login_lay.addWidget(self._btn_login)
        login_lay.addStretch()

        self._reg_user_edit = QLineEdit()
        self._reg_pass_edit = _password()
        self._reg_confirm_edit = _password()
        self._btn_register = QPushButton("Tạo tài khoản")
        self._btn_register.setObjectName("primary")
        self._btn_register.clicked.connect(self._on_register)
        hint = QLabel(f"Mật khẩu {self.MIN_PASSWORD}–{self.MAX_PASSWORD} ký tự. Mật khẩu không được lưu trên giao diện.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        reg_form = QFormLayout()
        reg_form.addRow("Tên đăng nhập", self._reg_user_edit)
        reg_form.addRow("Mật khẩu", self._reg_pass_edit)
        reg_form.addRow("Nhập lại mật khẩu", self._reg_confirm_edit)
        register = QWidget()
        reg_lay = QVBoxLayout(register)
        reg_lay.addLayout(reg_form)
        reg_lay.addWidget(hint)
        reg_lay.addWidget(self._btn_register)
        reg_lay.addStretch()

        self._tabs = QTabWidget()
        self._tabs.addTab(login, "Đăng nhập")
        self._tabs.addTab(register, "Đăng ký")
        self._tabs.setMaximumWidth(460)

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()
        self._info_label = QLabel("")
        self._info_label.setStyleSheet(
            "color: #047857; background: #DCFCE7; border: 1px solid #A7F3D0; "
            "border-radius: 8px; padding: 6px 10px; font-weight: 700;"
        )
        self._info_label.hide()
        self._btn_back = QPushButton("Ngắt kết nối")
        self._btn_back.clicked.connect(self.back_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 32, 32, 24)
        layout.addStretch()
        layout.addWidget(self._tabs, 0)
        layout.addWidget(self._error_label)
        layout.addWidget(self._info_label)
        layout.addStretch()
        layout.addWidget(self._btn_back)

    # ----------------------------------------------------------- handlers
    def _on_login(self) -> None:
        user, password = self._login_user_edit.text().strip(), self._login_pass_edit.text()
        if not user or not password:
            self.set_error("Vui lòng nhập tên đăng nhập và mật khẩu.")
            return
        self.clear_error()
        self.login_requested.emit(user, password)

    def _on_register(self) -> None:
        user = self._reg_user_edit.text().strip()
        password, confirm = self._reg_pass_edit.text(), self._reg_confirm_edit.text()
        if not user or not password:
            self.set_error("Vui lòng nhập tên đăng nhập và mật khẩu.")
        elif password != confirm:
            self.set_error("Mật khẩu nhập lại không khớp.")
        elif not self.MIN_PASSWORD <= len(password) <= self.MAX_PASSWORD:
            self.set_error(f"Mật khẩu phải dài {self.MIN_PASSWORD}–{self.MAX_PASSWORD} ký tự.")
        else:
            self.clear_error()
            self.register_requested.emit(user, password)

    # ----------------------------------------------------------------- API
    def set_error(self, text: str) -> None:
        self._info_label.hide()
        self._error_label.setText(text)
        self._error_label.show()

    def clear_error(self) -> None:
        self._error_label.clear()
        self._error_label.hide()

    def set_info(self, text: str) -> None:
        self.clear_error()
        self._info_label.setText(text)
        self._info_label.show()

    def set_loading(self, loading: bool) -> None:
        self._loading = loading
        self._btn_login.setEnabled(not loading)
        self._btn_register.setEnabled(not loading)

    def show_login_tab(self, username: str = "") -> None:
        self._tabs.setCurrentIndex(0)
        if username:
            self._login_user_edit.setText(username)
            self._login_pass_edit.setFocus()

    def clear_fields(self) -> None:
        for edit in (self._login_user_edit, self._login_pass_edit, self._reg_user_edit,
                     self._reg_pass_edit, self._reg_confirm_edit):
            edit.clear()
