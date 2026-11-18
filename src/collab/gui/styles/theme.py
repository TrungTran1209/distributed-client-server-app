"""Dark flat theme for the desktop GUI (single consistent QSS palette)."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

BG = "#1e1e2e"
SURFACE = "#181825"
CARD = "#2a2b3d"
BORDER = "#3b3d52"
TEXT = "#cdd6f4"
MUTED = "#8a8fb0"
ACCENT = "#89b4fa"
SUCCESS = "#a6e3a1"
ERROR = "#f38ba8"
WARNING = "#fab387"

STATUS_COLORS = {"success": SUCCESS, "error": ERROR, "warning": WARNING, "info": ACCENT, "muted": MUTED}

QSS = f"""
QWidget {{ background: {BG}; color: {TEXT}; font-size: 13px; }}
QMainWindow, QDialog {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-size: 30px; font-weight: 700; }}
QLabel#subtitle {{ color: {MUTED}; font-size: 14px; }}
QLabel#error {{ color: {ERROR}; }}
QLabel#hint {{ color: {MUTED}; font-size: 12px; }}
QLabel#banner {{ background: {ERROR}; color: {SURFACE}; padding: 8px 12px; font-weight: 600; }}
QFrame#sidebar, QWidget#sidebar {{ background: {SURFACE}; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 10px; }}
QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 7px 16px;
}}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:focus {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; background: {SURFACE}; border-color: {SURFACE}; }}
QPushButton#primary {{ background: {ACCENT}; color: {SURFACE}; border: none; font-weight: 600; }}
QPushButton#primary:hover {{ background: #a6c8ff; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {MUTED}; }}
QPushButton#danger {{ background: {ERROR}; color: {SURFACE}; border: none; font-weight: 600; }}
QPushButton#danger:disabled {{ background: {BORDER}; color: {MUTED}; }}
QPushButton#hero {{ font-size: 16px; font-weight: 600; padding: 22px 28px; border-radius: 10px; }}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 8px;
    selection-background-color: {ACCENT}; selection-color: {SURFACE};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QTextEdit:disabled {{ color: {MUTED}; }}
QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px; outline: 0; }}
QListWidget::item {{ padding: 8px 10px; }}
QListWidget::item:selected {{ background: {BORDER}; color: {TEXT}; }}
QListWidget::item:hover {{ background: {CARD}; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: {SURFACE}; padding: 8px 18px; border: 1px solid {BORDER}; border-bottom: none; }}
QTabBar::tab:selected {{ background: {CARD}; color: {ACCENT}; }}
QProgressBar {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 5px; text-align: center; height: 16px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 8px; margin-top: 12px; padding-top: 10px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}
QScrollArea {{ border: none; }}
QStatusBar {{ background: {SURFACE}; color: {MUTED}; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}
QScrollBar:vertical {{ background: {SURFACE}; width: 10px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def status_style(kind: str) -> str:
    """Inline stylesheet for a status label of type success/error/warning/info/muted."""
    return f"color: {STATUS_COLORS.get(kind, TEXT)}; font-weight: 600;"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
