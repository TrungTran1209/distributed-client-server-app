"""Application entry point — launches the main window."""
from __future__ import annotations

import sys


def main() -> None:  # pragma: no cover
    """Start the PySide6 application."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    app.setApplicationName("Collab")
    app.setOrganizationName("CollabProject")
    # Main window import deferred so that this module is importable without a display
    # from collab.gui.windows.main_window import MainWindow
    # win = MainWindow()
    # win.show()
    sys.exit(app.exec())
