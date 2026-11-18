"""Bootstrap for the standalone LumiChat Server Console."""

from __future__ import annotations

import sys


def main() -> None:  # pragma: no cover - requires display
    from PySide6.QtWidgets import QApplication

    from .controllers.server_controller import ServerController
    from .server_window import ServerMainWindow
    from .styles.theme import APP_BRAND, apply_theme

    app = QApplication(sys.argv)
    app.setApplicationName(f"{APP_BRAND} Server")
    app.setOrganizationName(APP_BRAND)
    apply_theme(app)
    win = ServerMainWindow(ServerController())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":  # pragma: no cover
    main()
