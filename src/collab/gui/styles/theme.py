"""Vibrant Daylight Theme for LumiChat Desktop (Client & Server Console).
Inspired by clean modern Figma SaaS & Messaging design systems.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

APP_BRAND = "LumiChat"

BG = "#F8FAFC"
SURFACE = "#FFFFFF"
CARD = "#FFFFFF"
SUBTLE = "#F1F5F9"
BORDER = "#E2E8F0"
BORDER_STRONG = "#CBD5E1"
TEXT = "#0F172A"
MUTED = "#64748B"

ACCENT = "#4F46E5"       # Vibrant Electric Indigo
ACCENT_HOVER = "#4338CA"
ACCENT_LIGHT = "#EEF2FF"
SKY = "#0EA5E9"          # Sky Cyan
SKY_LIGHT = "#E0F2FE"
CORAL = "#F43F5E"        # Vibrant Coral Rose
SUCCESS = "#10B981"      # Fresh Emerald Green
SUCCESS_LIGHT = "#ECFDF5"
ERROR = "#EF4444"        # Vibrant Rose Red
ERROR_LIGHT = "#FEF2F2"
WARNING = "#F59E0B"      # Warm Amber
WARNING_LIGHT = "#FFFBEB"
PURPLE = "#7C3AED"       # Modern Violet
PURPLE_LIGHT = "#F3E8FF"

STATUS_COLORS = {
    "success": "#059669",
    "error": ERROR,
    "warning": "#D97706",
    "info": ACCENT,
    "muted": MUTED,
}

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", -apple-system, "Inter", Arial, sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{
    background: {BG};
}}
QLabel {{
    background: transparent;
    color: {TEXT};
}}
QLabel#title {{
    font-size: 26px;
    font-weight: 800;
    color: {ACCENT};
    letter-spacing: -0.5px;
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 13px;
    font-weight: 500;
}}
QLabel#error {{
    color: {ERROR};
    background: {ERROR_LIGHT};
    border: 1px solid #FECACA;
    border-radius: 9px;
    padding: 7px 12px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {MUTED};
    font-size: 12px;
}}
QWidget#banner, QLabel#banner {{
    background: {ERROR_LIGHT};
    color: #B91C1C;
    border: 1px solid #FECACA;
    border-radius: 9px;
    padding: 8px 14px;
    font-weight: 600;
}}
QFrame#sidebar, QWidget#sidebar {{
    background: {SURFACE};
    border-right: 1px solid {BORDER};
}}
QFrame#card, QWidget#card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QPushButton {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{
    background: {SUBTLE};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background: {ACCENT_LIGHT};
}}
QPushButton:disabled {{
    color: #94A3B8;
    background: {SUBTLE};
    border-color: {BORDER};
}}
QPushButton#primary {{
    background: {ACCENT};
    color: #FFFFFF;
    border: none;
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
    color: #FFFFFF;
}}
QPushButton#primary:disabled {{
    background: #CBD5E1;
    color: #F8FAFC;
}}
QPushButton#accent_coral {{
    background: {CORAL};
    color: #FFFFFF;
    border: none;
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#accent_coral:hover {{
    background: #E11D48;
    color: #FFFFFF;
}}
QPushButton#accent_coral:disabled {{
    background: #FDA4AF;
    color: #FFFFFF;
}}
QPushButton#danger {{
    background: {ERROR};
    color: #FFFFFF;
    border: none;
    font-weight: 700;
    padding: 9px 18px;
}}
QPushButton#danger:hover {{
    background: #DC2626;
}}
QPushButton#danger:disabled {{
    background: #FECACA;
    color: #FFFFFF;
}}
QPushButton#hero {{
    background: {SURFACE};
    color: {TEXT};
    border: 2px solid {BORDER};
    font-size: 15px;
    font-weight: 700;
    padding: 20px 26px;
    border-radius: 14px;
}}
QPushButton#hero:hover {{
    border-color: {ACCENT};
    background: {ACCENT_LIGHT};
    color: {ACCENT};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER_STRONG};
    border-radius: 9px;
    padding: 7px 11px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {ACCENT};
    background: #FFFFFF;
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background: {SUBTLE};
    color: #94A3B8;
}}
QListWidget, QTableWidget, QTreeWidget {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    gridline-color: {SUBTLE};
    outline: 0;
}}
QHeaderView::section {{
    background: {SUBTLE};
    color: #334155;
    font-weight: 700;
    font-size: 12px;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 10px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 7px;
    margin: 2px 4px;
}}
QListWidget::item:selected {{
    background: {ACCENT_LIGHT};
    color: {ACCENT};
    font-weight: 700;
}}
QListWidget::item:hover {{
    background: {SUBTLE};
}}
QTreeWidget::item {{
    padding: 5px 6px;
    border-radius: 4px;
}}
QTreeWidget::item:selected {{
    background: {ACCENT_LIGHT};
    color: {ACCENT};
    font-weight: 700;
}}
QTreeWidget::item:hover {{
    background: {SUBTLE};
}}
QTabWidget::pane {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background: {SUBTLE};
    color: {MUTED};
    padding: 9px 20px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 9px;
    border-top-right-radius: 9px;
    margin-right: 4px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {SURFACE};
    color: {ACCENT};
    font-weight: 700;
}}
QProgressBar {{
    background: {SUBTLE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    text-align: center;
    font-weight: 700;
    height: 18px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {SKY}, stop:1 {ACCENT});
    border-radius: 7px;
}}
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: 700;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: {ACCENT};
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QStatusBar {{
    background: {SURFACE};
    color: {MUTED};
    border-top: 1px solid {BORDER};
    padding: 4px;
}}
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
}}
QScrollBar:vertical {{
    background: {BG};
    width: 8px;
    border-radius: 4px;
    margin: 2px 0 2px 0;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #94A3B8;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG};
    height: 8px;
    border-radius: 4px;
    margin: 0 2px 0 2px;
}}
QScrollBar::handle:horizontal {{
    background: #CBD5E1;
    border-radius: 4px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: #94A3B8;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
"""


def status_style(kind: str) -> str:
    """Inline stylesheet for a status label of type success/error/warning/info/muted."""
    return f"color: {STATUS_COLORS.get(kind, TEXT)}; font-weight: 700;"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
