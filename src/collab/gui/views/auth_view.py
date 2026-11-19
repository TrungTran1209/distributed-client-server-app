"""Login / registration screen with vibrant modern Figma daylight card styling."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QHBoxLayout,
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

        # Card container
        card = QFrame()
        card.setObjectName("card")
        card.setMaximumWidth(520)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(28, 26, 28, 26)
        card_lay.setSpacing(16)

        # Header Badge & Title
        auth_badge = QLabel("🔐 XÁC THỰC MÃ HÓA SCRYPT + SALT")
        auth_badge.setStyleSheet(
            "color: #4F46E5; font-weight: 800; font-size: 11px; letter-spacing: 0.8px; background: transparent;"
        )
        auth_title = QLabel("Đăng nhập hoặc Tạo tài khoản")
        auth_title.setStyleSheet("font-size: 20px; font-weight: 800; color: #0F172A; background: transparent;")
        auth_sub = QLabel("Mật khẩu được dẫn xuất bằng scrypt với salt 16-byte ngẫu nhiên và so sánh thời gian hằng số.")
        auth_sub.setStyleSheet("color: #64748B; font-size: 12px; background: transparent;")
        auth_sub.setWordWrap(True)

        card_lay.addWidget(auth_badge)
        card_lay.addWidget(auth_title)
        card_lay.addWidget(auth_sub)

        # Login Form Tab
        self._login_user_edit = QLineEdit()
        self._login_user_edit.setPlaceholderText("Nhập tên đăng nhập của bạn")
        self._login_pass_edit = _password()
        self._login_pass_edit.setPlaceholderText("Nhập mật khẩu an toàn")
        self._btn_login = QPushButton("Đăng nhập An toàn ➤")
        self._btn_login.setObjectName("primary")
        self._btn_login.clicked.connect(self._on_login)
        self._login_pass_edit.returnPressed.connect(self._btn_login.click)

        login_form = QFormLayout()
        login_form.setSpacing(12)
        login_form.addRow("Tên đăng nhập", self._login_user_edit)
        login_form.addRow("Mật khẩu", self._login_pass_edit)

        login = QWidget()
        login_lay = QVBoxLayout(login)
        login_lay.setContentsMargins(14, 16, 14, 14)
        login_lay.setSpacing(14)
        login_lay.addLayout(login_form)
        login_lay.addWidget(self._btn_login)
        login_lay.addStretch()

        # Register Form Tab
        self._reg_user_edit = QLineEdit()
        self._reg_user_edit.setPlaceholderText("Tên đăng nhập mới (chữ, số, gạch dưới)")
        self._reg_pass_edit = _password()
        self._reg_pass_edit.setPlaceholderText(f"Tối thiểu {self.MIN_PASSWORD} ký tự")
        self._reg_confirm_edit = _password()
        self._reg_confirm_edit.setPlaceholderText("Nhập lại chính xác mật khẩu")
        self._btn_register = QPushButton("Tạo tài khoản Mới ➤")
        self._btn_register.setObjectName("primary")
        self._btn_register.clicked.connect(self._on_register)
        self._reg_confirm_edit.returnPressed.connect(self._btn_register.click)

        hint = QLabel(
            f"ℹ️ Mật khẩu dài {self.MIN_PASSWORD}–{self.MAX_PASSWORD} ký tự. "
            "Mật khẩu không bao giờ lưu trữ dạng thô và không hiển thị trên log máy chủ."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)

        reg_form = QFormLayout()
        reg_form.setSpacing(12)
        reg_form.addRow("Tên đăng nhập mới", self._reg_user_edit)
        reg_form.addRow("Mật khẩu", self._reg_pass_edit)
        reg_form.addRow("Nhập lại mật khẩu", self._reg_confirm_edit)

        register = QWidget()
        reg_lay = QVBoxLayout(register)
        reg_lay.setContentsMargins(14, 16, 14, 14)
        reg_lay.setSpacing(14)
        reg_lay.addLayout(reg_form)
        reg_lay.addWidget(hint)
        reg_lay.addWidget(self._btn_register)
        reg_lay.addStretch()

        self._tabs = QTabWidget()
        self._tabs.addTab(login, "🔑 Đăng nhập")
        self._tabs.addTab(register, "✨ Tạo tài khoản")

        self._error_label = QLabel("")
        self._error_label.setObjectName("error")
        self._error_label.setWordWrap(True)
        self._error_label.hide()

        self._info_label = QLabel("")
        self._info_label.setStyleSheet(
            "color: #047857; background: #DCFCE7; border: 1px solid #A7F3D0; "
            "border-radius: 9px; padding: 7px 12px; font-weight: 700;"
        )
        self._info_label.hide()

        self._btn_back = QPushButton("← Ngắt kết nối Máy chủ")
        self._btn_back.clicked.connect(self.back_requested)

        card_lay.addWidget(self._tabs)
        card_lay.addWidget(self._error_label)
        card_lay.addWidget(self._info_label)
        card_lay.addWidget(self._btn_back)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(card)

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
        for edit in (
            self._login_user_edit,
            self._login_pass_edit,
            self._reg_user_edit,
            self._reg_pass_edit,
            self._reg_confirm_edit,
        ):
            edit.clear()
