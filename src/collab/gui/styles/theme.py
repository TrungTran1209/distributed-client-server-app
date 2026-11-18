"""Vibrant Daylight Theme for LumiChat Desktop (Client & Server Console)."""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

APP_BRAND = "LumiChat"

BG = "#F8FAFC"
SURFACE = "#FFFFFF"
CARD = "#FFFFFF"
SUBTLE = "#F1F5F9"
BORDER = "#E2E8F0"
TEXT = "#0F172A"
MUTED = "#64748B"

ACCENT = "#4F46E5"       # Vibrant Indigo
SKY = "#0EA5E9"          # Sky Cyan
CORAL = "#F97316"        # Energetic Coral Orange
SUCCESS = "#10B981"      # Fresh Emerald Green
ERROR = "#EF4444"        # Vibrant Rose Red
WARNING = "#F59E0B"      # Warm Amber

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
    font-family: "Segoe UI", "Inter", Arial, sans-serif;
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
    font-size: 28px;
    font-weight: 800;
    color: {ACCENT};
}}
QLabel#subtitle {{
    color: {MUTED};
    font-size: 14px;
}}
QLabel#error {{
    color: {ERROR};
    background: #FEF2F2;
    border: 1px solid #FECACA;
    border-radius: 8px;
    padding: 6px 10px;
    font-weight: 600;
}}
QLabel#hint {{
    color: {MUTED};
    font-size: 12px;
}}
QWidget#banner, QLabel#banner {{
    background: #FEF2F2;
    color: #B91C1C;
    border: 1px solid #FECACA;
    border-radius: 8px;
    padding: 8px 12px;
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
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {SUBTLE};
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background: #E0E7FF;
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
}}
QPushButton#primary:hover {{
    background: #4338CA;
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
}}
QPushButton#accent_coral:hover {{
    background: #EA580C;
    color: #FFFFFF;
}}
QPushButton#accent_coral:disabled {{
    background: #FED7AA;
    color: #FFFFFF;
}}
QPushButton#danger {{
    background: {ERROR};
    color: #FFFFFF;
    border: none;
    font-weight: 700;
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
    background: #EEF2FF;
    color: {ACCENT};
}}
QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QComboBox {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid #CBD5E1;
    border-radius: 8px;
    padding: 7px 10px;
    selection-background-color: {ACCENT};
    selection-color: #FFFFFF;
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border: 2px solid {ACCENT};
}}
QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled {{
    background: {SUBTLE};
    color: #94A3B8;
}}
QListWidget, QTableWidget {{
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
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 8px 10px;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 2px 4px;
}}
QListWidget::item:selected {{
    background: #EEF2FF;
    color: {ACCENT};
    font-weight: 700;
}}
QListWidget::item:hover {{
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
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
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
    border-radius: 7px;
    text-align: center;
    font-weight: 700;
    height: 18px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {SKY}, stop:1 {ACCENT});
    border-radius: 6px;
}}
QGroupBox {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 12px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
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
}}
QSplitter::handle {{
    background: {BORDER};
    width: 1px;
}}
QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1;
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: #94A3B8;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
"""


def status_style(kind: str) -> str:
    """Inline stylesheet for a status label of type success/error/warning/info/muted."""
    return f"color: {STATUS_COLORS.get(kind, TEXT)}; font-weight: 700;"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(QSS)
