"""Bootstrap for the standalone LumiChat Client Application."""

from __future__ import annotations

import sys


def main() -> None:  # pragma: no cover - requires display
    from PySide6.QtWidgets import QApplication

    from .client_window import ClientMainWindow
    from .controllers.client_controller import ClientController
    from .styles.theme import APP_BRAND, apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_BRAND} Client")
    app.setOrganizationName(APP_BRAND)
    apply_theme(app)
    win = ClientMainWindow(ClientController(auto_accept=True))
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    main()
