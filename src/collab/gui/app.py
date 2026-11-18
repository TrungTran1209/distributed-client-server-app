"""Desktop application bootstrap."""
from __future__ import annotations

import sys


def main() -> None:  # pragma: no cover - requires a display
    from PySide6.QtWidgets import QApplication

    from .controllers.client_controller import ClientController
    from .controllers.server_controller import ServerController
    from .main_window import MainWindow
    from .styles.theme import apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName("Collab")
    app.setOrganizationName("CollabProject")
    apply_theme(app)
    window = MainWindow(ServerController(), ClientController())
    window.show()
    sys.exit(app.exec())
